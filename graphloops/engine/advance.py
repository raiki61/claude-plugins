"""進行——機械の節を走らせ、扇を広げ、回す側に渡す節（instance）を発行する。"""
import os
import json
import pathlib
import sys

from . import pointers
from .render import FILE_CAP, Renderer, node_prompt
from .rules import hook, registry
from .schema import graph_text, validate_schema
from .util import ANSWER_ACTIONS, IN_ROUND_ACTIONS, TERMINAL_STATUS, die, dump, now, read_json, safe_name, sha, write_json
from .role_run import WRITE_TOOLS, tooled_permission
from .validator import agent_def, finalize, report_accepts, run_validator, deliver_mode

ENGINE_PRE = ("finalize",)  # 節の pre で engine が解釈する値。graphcheck が import して綴り違いを落とす
# launch.isolated / launch.tooled の argv・resume・via の穴。engine が埋められるのはこの語だけ——graphcheck が import して知らない穴と、
# 役の定義に無い model / effort を静的に落とす（以前は起こす関数の die と format の KeyError でしか出なかった）。
# python / plugin_root は役でも graph でもなく **engine 自身しか知らない事実**（自分を走らせているインタプリタと、
# 自分が入っている場所）。「起動の語は graph が宣言する」線は動かさない——graph が使うと書いたときだけ埋まる。
# tools / allowed_tools / permission_mode は道具つきの役の分（役の定義の道具と、engine の role_run.tooled_permission から埋める）。
# session_id は同じ会話を続ける語（--resume）の穴で、続ける会話が決まるまでは '{session_id}' のまま残す（role_run が埋める）。
LAUNCH_HOLES = ("model", "effort", "role_file", "prompt_file", "out_path", "python", "plugin_root",
                "tools", "allowed_tools", "permission_mode", "session_id")
LAUNCH_MAY_BE_EMPTY = ("session_id",)  # 空でも起こせる穴（続ける会話がまだ無い）
PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[1]  # engine/ の親＝プラグインの根（scripts/ の隣）
ITEM_INLINE = 1000  # 扇の項目のうち instance（state.json と next の出力）に残す欄の上限（直列化した UTF-8 のバイト）。
# 超える欄は items/ のファイルにだけ置く。**バイトで測る**——実測 2026-09-18: 1 束 1,716 バイト＝
# 約 570 字の材料が、字数の 1000 を超えず 5 束とも素通りした（バイトで持つ上限の先例は render.py の FILE_CAP）

# 「育った」と言い始める絶対量の下限。**切らないことは『いくらでも貼ってよい』ではない**
# ——回す側の文脈は有限で、周ごとに単調増加する穴は誰にも見えないまま育つ（実測 2026-09-13:
# report.human_items が record.process と loop を丸ごと読み、6 周目で 1,120 KB。上限の無い経路
# （回す側・遮断系・path 渡し）なので truncated にも出ず、記録にも報告にも痕跡が 1 つも無かった）。
# この線より下は倍率が跳ねても言わない——小さい節の 1 KB → 2 KB は育ちではなく普通の揺れ。
# 台本が差し替えられるようにする（環境変数）。**実物の next を通す腕が要る**——部品を直に呼ぶ腕だけの
# とき、痕跡を積む配線（`if grew:`）を殺しても全件緑だった（実測 2026-09-14。その腕は
# graphloops/tests/simulate.py:test_prompt_growth の後半——実物の next を 1 本通す側に在る）。
# 写しの graph を作って 100 KB の穴を育てるより、線を下げて実物の run を 1 本通す方が安い。
PROMPT_NOTICE = int(os.environ.get("GL_PROMPT_NOTICE") or 100_000)
# 育ったと呼ぶ倍率。**線と一緒に差し替えられる**——台本の穴は周をまたいでも 1.05 倍までしか育たない
# （実測 2026-09-14: 標準の筋書きで p2.integrate が 6,737 → 7,055 バイト）ので、線だけ下げても配線を通らない。
# 2 つとも下げて初めて、実物の next が痕跡を積む分岐を踏む。既定は本番の値で、環境変数は台本だけが使う。
PROMPT_GROWTH_RATIO = float(os.environ.get("GL_PROMPT_GROWTH_RATIO") or 1.5)


def tooled_launchable(d):
    """道具つきの役を engine が起こせるか。起こせないのは、定義が道具の一覧を持たない（全部の道具を継ぐ）役・
    ファイルを書く道具を持つ役・モデルか effort を名指ししない役——どれも回す側が Agent で起こす。
    何でもできる子を engine の中から起こさない（能力の上限は role_run.WRITE_TOOLS の注記）。"""
    return ("*" not in d["tools"] and not any(x in WRITE_TOOLS for x in d["tools"])
            and d.get("model") not in (None, "", "inherit") and bool(d.get("effort")))


def launch_spec(b, inst, d, resume_sid=None):
    """役を engine の中で起こす語（argv・続きの語・材料）。起こせない役なら None（回す側が Agent で起こす）。

    **道具ゼロの役（遮断系）**は Agent ツールで起こさない——ハーネスは subagent に CLAUDE.md 階層を注入し、**それを止める
    設定が無い**（公式文書 code.claude.com/docs/en/sub-agents、2026-09-12 取得: "Explore and Plan are the only subagents
    that omit CLAUDE.md and git status. There is no frontmatter field or per-agent setting to change which agents skip
    them."）。実測 2026-09-12: 道具ゼロの cold-reader が利用者の CLAUDE.md の 1 項目を逐語で引用した。setting source
    ごと外せるのは CLI だけ（同日の対照実験: フラグ無しでは目印が見え、--setting-sources "" を付けると消えた）。

    **道具つきの役**も同じ CLI の同じ綴りで起こす（graph の launch.tooled）。回す側と役の間に中継の AI を挟むと、
    書いていないのに『書いた』と返す・続きの返答が回す側へ戻る・完了の知らせが迷う、が起きた（実測 2026-09-24〜25）。
    役の本文は道具ゼロの役と同じ roles/<役>.txt から system prompt に足し、道具・モデル・effort・権限は argv に並べる——
    **権限に関わる事実を全部 argv に置く**（--agents の定義ファイルは permissionMode や hooks を持てるので、柵の読まない
    ファイルに権限が移る）。子はプラグインを読まない（--setting-sources ""）ので、プラグインの名前でも役は解決しない。

    起動の語（コマンド名・フラグ）は graph が宣言する——engine はハーネスの語彙を持たない。
    `via` は、解決した argv の**前に**置く語（既定は空）。子は対話の claude の認証を継がないので、graph はここに
    薄い層（scripts/with-auth.py）を宣言して認証だけを足す。**argv の中に混ぜず前置に分けてある**のは、`argv[0]` の
    PATH 解決と `missing` の報せを前置が隠さないため。

    resume_sid を渡すと、同じ会話を続ける語（spec の resume）で起こす（same_context_as の節）。続ける語を graph が
    宣言しない形なら None（続けられない）。
    """
    isolated = d["tools"] == []
    kind = "isolated" if isolated else "tooled"
    spec = b.graph.get("launch", {}).get(kind)
    if not spec:
        if isolated:
            die(f"{inst['id']}: 道具ゼロの役 '{inst['agent_type']}' を起こすのに graph の launch.isolated が無い"
                "（Agent ツールで起こすと CLAUDE.md が注入され、遮断が名ばかりになる）")
        return None
    if resume_sid and not spec.get("resume"):
        return None
    role = safe_name(inst["agent_type"])
    rdir = b.dir / "roles"
    rdir.mkdir(parents=True, exist_ok=True)
    sub = dict.fromkeys(LAUNCH_HOLES, "")
    sub.update(model=d.get("model") or "", effort=d.get("effort") or "", prompt_file=inst["prompt_file"],
               out_path=inst["out_path"], python=sys.executable, plugin_root=str(PLUGIN_ROOT),
               session_id=resume_sid or "{session_id}")
    role_file = rdir / (role + ".txt")
    role_file.write_text(d["body"], encoding="utf-8")
    sub["role_file"] = str(role_file)
    tools = []
    if not isolated:
        if not tooled_launchable(d):
            return None
        tools = list(d["tools"])
        mode, allowed = tooled_permission(tools)
        sub.update(tools=",".join(tools), allowed_tools=",".join(allowed), permission_mode=mode)
    words = list(spec["argv"]) + list(spec.get("resume") or []) + list(spec.get("via") or [])
    for k, v in sub.items():
        if not v and k not in LAUNCH_MAY_BE_EMPTY and any("{" + k + "}" in a for a in words):
            die(f"{inst['id']}: 起動に要る '{k}' が役の定義（{d['file']}）に無い")
    # PATH を引いて絶対パスに替える（起こす時の曖昧さを 1 つ減らす）。**見つからなくても落とさない**——
    # next は計画を出す所で、起こすのは回す側の環境である。ここで die にしたら、遮断系を一度も起こさない場
    # （台本の検査・別の機械での再開・記録を読むだけの用）まで動かなくなった（実測 2026-09-12: CI の 3 OS が
    # 全部赤。手元には claude が在るので緑だった）。実際に起こせないことは、launch が起こす瞬間に分かる。
    import shutil  # 起動する節でだけ要る（全サブコマンドの起動に掛けない）
    via = [a.format(**sub) for a in (spec.get("via") or [])]

    def resolve(words):
        argv = [a.format(**sub) for a in words]
        found = shutil.which(argv[0])
        return via + (([found] + argv[1:]) if found else argv), found

    argv, found = resolve(spec["resume"] if resume_sid else spec["argv"])
    launch = {"kind": kind, "argv": argv, "stdin": inst["prompt_file"],
              "resume_argv": resolve(spec["resume"])[0] if spec.get("resume") else None}
    if tools:
        launch["tools"] = tools
    if not found:
        launch["missing"] = argv[len(via)]  # この環境では起こせない。回す側と記録に見えるようにしておく
    return launch


def slim_item(item):
    """instance に残す項目——長い欄（貼る本文など）を落とした写しと、落とした欄の名前。

    **長さはその欄が instance に載る形で、UTF-8 のバイトで測る**（文字列はそのまま、それ以外は直列化して。
    字数では測らない）。文字列の欄だけ見ていたとき、配列・辞書の欄は何件あっても素通りし、扇の材料が
    next の出力に丸ごと出ていた（実測 2026-09-18: research-loop の p1.checker の材料は
    {"key": …, "claims": [ …主張… ]} で、25 主張・5 クラスタの波の next が 15,904 バイト。通常の波は約 4 KB）。
    しかも落ちた欄が無いので item_omitted も空のまま——外から見ると『削る仕組みが働いて、削る物が無かった』と
    区別が付かない。**空振りしていることが見えない柵は、無い柵より悪い。**
    材料の正本は items/ のファイルで、役に渡るプロンプトはそこから埋まる（load_item）ので、ここで落として
    減るのは回す側の文脈だけである。

    **縛るのは写し全体の合計 1 段だけ。** 塞ぎたい害（next の出力量）は総量の話なので、柵の
    不変条件も総量で言う。欄ごとの上限と合計の 2 段にしていたとき、欄ごとの側は倒しても
    検査の色が変わらなかった——同じことを合計の側が既に言っていたからで、2 段目は柵でなく写しだった。
    落とすのは大きい欄から。**key だけは長さに関わらず残す**——扇の重複排除（emit_instance の
    呼び出し側）と台本が item["key"] を添字で読むので、落とすと診断文でなく traceback になる。
    """
    slim, omitted = dict(item), []
    while len(dump(slim).encode("utf-8")) > ITEM_INLINE:
        rest = [k for k in slim if k != "key"]
        if not rest:
            break  # key だけで超える材料は、落とす先が無いのでそのまま残す（下流が添字で読む）
        big = max(rest, key=lambda k: len(dump(slim[k]).encode("utf-8")))
        del slim[big]
        omitted.append(big)
    return slim, omitted


def load_item(inst, board_dir=None):
    """instance の項目の全部（items/ のファイルが正本。無ければ instance の item）。

    **保存済みの相対の綴りも開ける。** 置き場の綴りを入口で絶対化する前に作られた盤面は item_file に
    相対を持つので、別の cwd から開くと read_json が die する——新規の盤面だけ直して移行を置かないと、
    走っている run が次の next で止まる（実測 r3: cmd_done は元から正本読みで、その破れが next にも広がった）。
    board_dir を基準に開き直して救う。**救えたことは黙らない**: 綴りを絶対に直して盤面に書き戻し、
    次からは基準無しでも開ける（救い続ける経路を残さない）。
    """
    f = inst.get("item_file")
    if not f:
        return inst.get("item")
    p = pathlib.Path(f)
    if not p.is_file() and board_dir and "items" in p.parts:
        # **盤面の綴りを頭に足さない。** engine は `str(b.dir / "items" / …)` と書くので、保存された綴りは
        # 盤面の綴りを**含んでいる**——頭に足すと盤面の名前が二重になり、救済は必ず外れた
        # （実測 r9: 台本だけが engine の書かない綴り（盤面の根からの相対）を食わせて緑になっていた）。
        # 盤面の下の `items/…` を組み直す: 保存された綴りのうち items 以降だけを使う。
        tail = p.parts[p.parts.index("items"):]
        alt = pathlib.Path(board_dir).joinpath(*tail)
        if alt.is_file():
            inst["item_file"] = str(alt.resolve())
            return read_json(inst["item_file"])
    return read_json(f)


def agent_type_of(b, n):
    if n.get("agent_type"):
        return n["agent_type"]  # 別プラグインの agent（接頭ごと書く）
    return (b.plugin + ":" + n["run_by"]) if b.plugin else n["run_by"]


def prompt_growth(b, nid, prompt_bytes):
    """前の周の同じ節と比べて『育った』か。育っていれば記録に残す 1 行、そうでなければ None。

    **切らない経路でも大きさは測る。** ただし見るのは大きさそのものではなく**育ち方**——差分を丸ごと
    貼る節（p1.hygiene の 912 KB）は大きくて正しく、周ごとに増える節（report.human_items）は小さくても
    間違っている。大きさで線を引くと、正しく大きい節が毎周鳴って、育っている節がその中に紛れる。

    比べる相手は**同じ節の前の周**だけ。節をまたいで比べると、扇の項目ごとに大きさが違う節が常に鳴る。
    """
    prev = [i["prompt_bytes"] for rd in b.state["rounds"] if rd["round"] < b.round
            for i in rd["instances"].values() if i["node"] == nid and i.get("prompt_bytes")]
    if not prev or prompt_bytes <= PROMPT_NOTICE or prompt_bytes <= max(prev) * PROMPT_GROWTH_RATIO:
        return None
    return {"node": nid, "round": b.round, "bytes": prompt_bytes, "was": max(prev)}


ENGINE_HELPERS = ("parallel-pr.py",)   # engine に同梱の走らせる語（scripts/ の下）。承認なしで走らせてよいのはこれだけ


def helper_argv(name, args=()):
    """同梱の語の argv——engine 自身のインタプリタと、engine の置き場の scripts/<name>"""
    return [sys.executable, str(PLUGIN_ROOT / "scripts" / name), *args]


def engine_run_entry(b, n):
    fn = registry(b.rules, "ENGINE_RUNS").get(n["engine_run"]["builtin"])
    if not fn:
        die(f"engine_run.builtin '{n['engine_run']['builtin']}' が rules の ENGINE_RUNS に無い")
    return fn


def plan_engine_run(b, nid, n, inst, fallback=None):
    """走らせるだけの節（graph の engine_run）を、engine が走らせる instance（mode=engine_run）にするか、任せ先の節のまま
    出すかを決める。決めるのは rules の ENGINE_RUNS[builtin].plan で、返りは 4 つの形のどれか:
      {"steps": [{name, argv}], "sha": …}   対象リポジトリの宣言の語（launch が人の承認を確かめ直してから走らせる）
      {"helper": 名前, "args": […]}          engine に同梱の語（ENGINE_HELPERS。承認は要らない）
      {"blocked": 理由}                      走らせないが、engine が返答を組む（例: 宣言は在るが未承認）
      {"fallback": 理由}                     任せ先の節として出す（理由は instance と、rules の fallback が記録に残す）
    fallback を渡されたら計画を立てずに任せ先へ落とす（engine の組んだ返答が拒まれた・役の判断が要る結果が出た）。
    **走らせる語は emit の時点で instance に固める**——launch は固めた語だけを走らせ、読んだ時と走らせる時のずれを作らない"""
    er = engine_run_entry(b, n)
    plan = {"fallback": fallback} if fallback else er["plan"](b, nid)
    if "fallback" in plan:
        inst["engine_fallback"] = plan["fallback"]
        if er.get("fallback"):
            er["fallback"](b, nid, plan["fallback"])
        return
    if "helper" in plan:
        if plan["helper"] not in ENGINE_HELPERS:
            die(f"{nid}: 同梱の語 '{plan['helper']}' は ENGINE_HELPERS に無い")
        steps = [{"name": plan["helper"], "argv": helper_argv(plan["helper"], plan.get("args") or [])}]
    else:
        steps = plan.get("steps") or []
    inst.pop("delegate", None)
    inst["mode"] = "engine_run"
    inst["launch"] = {"kind": "engine_run", "builtin": n["engine_run"]["builtin"], "steps": steps,
                      "sha": plan.get("sha"), "blocked": plan.get("blocked"), "cwd": plan.get("cwd")}


def emit_instance(b, nid, item=None, suffix="", attempt=1, engine_fallback=None):
    n = b.nodes[nid]
    iid = nid + (f"[{item['key']}]" if item else "") + suffix
    emitted = now()
    try:
        tpl = node_prompt(b.state["graph"], n)
    except OSError as e:
        die(f"{nid}: prompt_file が読めない: {e}")
    ctx = b.ctx(item)
    # 節そのものの宣言をプロンプトから引けるようにする（{{node.skills}}）。**正本を 1 か所にするための口**
    # ——レンズの一覧を散文へ手で写すと、正本を直した周に写しだけが古くなり、しかも役は写しの方を読む
    # （実測 2026-09-15: skills 配列に 3 本足したのにプロンプト側は 2 本しか名指ししていなかった）。
    # 渡すのは skills だけ——節の宣言を丸ごと開くと、schema も deps も役の目に入って指示と資料の境が消える。
    ctx["node"] = {"skills": n.get("skills", [])}
    if n.get("pre") == "finalize":
        # 報告の前に記録を仕上げて検証器を回す。通らなければこの節は出さない（fail loud）
        finalize(b)
        b.save()
        v = run_validator(b)
        accepts = report_accepts(b)
        if v["exit"] not in accepts:  # None（検証器が無い・動かない）も不合格——検査できない run を無検査で報告に進めない
            b.trace("validator_failed", exit=v["exit"], out=v["out"])
            die(f"{nid}: 記録が検証器を通らない（exit {v['exit']}）。engine か rules か節の出力の欠陥——record.json と trace.jsonl を見て直す（手当ては loop.py patch）:\n{v['out']}", 1)
        ctx["validation"] = v
        # 生出力は {{ref:raw}}（Board.ref）だけが渡す——ctx["raw"] は両 graph のどのプロンプトからも読まれておらず、
        # 報告の next で同じ出力を 209 回読み直していた（実測 2026-09-12）
    # 道具ゼロの役は別プロセスの CLI へ標準入力で流すので、貼る先の上限が無い＝切らない（cap=None）。
    # 上限は「Agent ツールのプロンプトに貼る」経路の性質で、engine の都合でもモデルの都合でもない。
    atype = None if b.is_runner(n) else agent_type_of(b, n)
    role_def = agent_def(atype) if atype else None
    role_def_missing = None
    if atype and ":" in atype and role_def is None:
        # 「定義が読めない」を「道具を持つ役」と同じ False に潰さない——遮断系かどうかが分からないまま Agent ツール
        # 経路に倒すと、2f2c081 が閉じた CLAUDE.md 注入がそのまま戻る（launch.isolated.argv の不在は die するのに、
        # 定義の不在だけが黙って落ちていた非対称。実測 2026-09-12: 空の CLAUDE_CONFIG_DIR で p1.hygiene が mode=agent に
        # なり notes は空だった）。graph 自身の plugin の役は定義が要る（遮断系はここにしか居ない）。別 plugin の役
        # （pr-review-toolkit 等）はこの機械に入っていないことが普通にある（実測: CI には無い）——止めずに、定義が
        # 無かった事実を instance と記録に残す（渡し方は paste＝貼れば必ず届く側）。接頭の無い組み込み agent は従来どおり。
        if atype.rpartition(":")[0] == b.plugin:
            die(f"{iid}: 役 '{atype}' の定義（agents/<役>.md）が解決できない——遮断系かどうかが決まらないので起こさない"
                "（plugin の置き場・<PLUGIN>_ROOT・CLAUDE_CONFIG_DIR を確かめよ）")
        role_def_missing = f"{atype} の定義がこの環境に無い（別 plugin）。道具は不明——遮断系としては扱わない。渡し方は paste"
        b.state.setdefault("role_def_missing", []).append({"instance": iid, "round": b.round, "agent_type": atype})
    isolated = role_def is not None and role_def["tools"] == []
    runner = b.is_runner(n)
    # engine が起こせる役か（launch_spec が語を組める役）。起こせる役の材料は標準入力で子へ流すので、貼る先の上限が無い
    launchable = not runner and role_def is not None and (
        isolated or bool(b.graph.get("launch", {}).get("tooled") and tooled_launchable(role_def)))
    # **上限を外す条件は「貼るか（deliver）」で、道具ゼロか（isolated）ではない。** 以前は isolated を見ていたが、
    # それは正本と相関するだけの代理だった——貼る先の上限は「Agent ツールのプロンプトに本文を貼る」経路の性質なので、
    # 役が自分でファイルを読む deliver=path と、自分の節を自分でやる runner には当たらない。代理を見ていたとき、
    # Read を持つ judge の入力だけが切られた（実測 2026-09-13: r1.minimality が 119,284→40,000、p2.diagnose が
    # 78,672→40,000、p2.history が 43,393→40,000。遮断系は 1 件も切られていない）。切られた側は自分が何を失ったか
    # 分からない（全文の置き場が本文に無い）ので、判定の質が落ちても誰も観測できなかった。
    deliver = None if runner else deliver_mode(atype, b.graph.get("deliver", {}).get("path_tools", []),
                                               paste_roles=b.graph.get("deliver", {}).get("paste_roles", []),
                                               tools=role_def["tools"] if role_def else None)
    # 貼る経路は「回す側でなく・遮断系でなく・deliver が paste」の 1 通りだけ。isolated を条件から落とすと、
    # 遮断系は deliver_mode が paste を返す（道具ゼロなので path_tools を持たない）ため切られる側に回る
    # ——最初にこの 3 つ目を落として台本が 2 件赤くなった（実測 2026-09-13: 45,118 バイトの本文が切られた）
    snap, offsets = pointers.snapshot(ctx, n.get("pointers"))
    r = Renderer(ctx, n.get("reads"), ref=b.ref,
                 cap=None if (runner or launchable or deliver == "path") else FILE_CAP, numbered=offsets)
    try:
        prompt = r.render(tpl)
    except KeyError as e:
        die(f"{nid}: {e}")
    unseen = sorted(set(offsets) - r.numbered_seen)
    if unseen:
        die(f"{nid}: pointers の from {unseen} を貼る穴がプロンプトに無い——番号が役に見えない（穴はその一覧のパスそのもので書け）")
    if n.get("schema"):
        # **引用符の断りを 1 行入れる。** 役の指摘はコード片や設定値をそのまま引くので、文字列値の中に
        # 生の " が入りやすい（実測 2026-09-15: cold-reader の初回の返答が `（"/code-review high" 等）` で
        # 折れ、60 秒ぶんの指摘 3 件が 1 件も記録に入らなかった）。落ちる先は done なので、役に言うのが一番安い。
        prompt += ("\n\n---\n返答はこの JSON Schema に合う JSON だけ（前後に文を付けない）。"
                   '文字列値の中の " は必ず \\" にエスケープしろ——生のまま入れると返答まるごとが'
                   "読めずに捨てられる:\n" + dump(n["schema"]))
    if r.truncated:
        b.state.setdefault("truncated", []).extend(f"{iid}: {t}" for t in r.truncated)
    pfile = b.dir / "prompts" / f"r{b.round}" / (safe_name(iid) + ".md")
    pfile.parent.mkdir(parents=True, exist_ok=True)
    pfile.write_text(prompt, encoding="utf-8")
    prompt_bytes = len(prompt.encode("utf-8"))
    grew = prompt_growth(b, nid, prompt_bytes)
    if grew:
        b.state.setdefault("growing_prompts", []).append({"instance": iid, "capped": r.cap is not None, **grew})
    inst = {
        "id": iid, "node": nid, "run_by": n["run_by"], "prompt_bytes": prompt_bytes,
        "mode": "runner" if runner else "agent",
        "agent_type": None if runner else agent_type_of(b, n),
        "prompt_file": str(pfile), "prompt_sha": sha(prompt), "item": item, "status": "pending", "emitted_at": emitted,
        # 返答の置き場（運び手がここへ書けば done は --output 無しで読む）。**本文を返す節（text）は .md**——
        # 拡張子が .json だと、Markdown を返す節で運び手が別名に書き、初回の done が『返答が無い』で必ず落ちた。
        # **起こし直した試行は置き場を分ける**（.a<試行>）——前の試行が遅れて書いても別のファイルに落ち、記録に入らない
        # （Temporal の task token が試行ごとに一意で、古い試行の完了の報告を受け付けないのと同じ締め出し）
        "out_path": str(b.dir / "out" / f"r{b.round}" / (safe_name(iid) + (f".a{attempt}" if attempt > 1 else "")
                                                         + (".md" if n.get("text") else ".json"))),
        "attempts": attempt,
        # 役が番号で指す一覧の名前の列（emit の時点で固める。done が番号を名前に戻すときに読む唯一の値）
        **({"pointers": snap} if snap else {}),
    }
    # **返答の置き場のディレクトリも engine が作る**——プロンプトの置き場だけ作っていたとき、運び手が
    # シェルのリダイレクトや mkdir をしない書き方で書くと、最初の done が『返答が無い』で必ず落ちた（実走の申し送り 2026-09-24）
    pathlib.Path(inst["out_path"]).parent.mkdir(parents=True, exist_ok=True)
    if item:
        # 項目の正本は items/ のファイル 1 つ。貼る本文はプロンプトに埋めた後なので、盤面と next の出力には長い欄を残さない
        ifile = b.dir / "items" / f"r{b.round}" / (safe_name(iid) + ".json")
        write_json(ifile, item)
        inst["item"], omitted = slim_item(item)
        inst["item_file"] = str(ifile)
        # **空でも常に書く。** 鍵ごと省くと『落ちる欄が無かった』と『逃がす仕組みを持たない engine が
        # 出した instance』が同じ形になり、逃がしが働いたかを盤面から機械で見る足場が無くなる
        inst["item_omitted"] = omitted
    if n.get("skills"):
        inst["skills"] = n["skills"]
    if runner and n.get("delegate"):
        # 回す側の節のうち、自分の文脈で抱えずに小さな役へ任せてよいもの（graph の宣言をそのまま渡す。engine は起こさない——
        # 起こすのは回す側で、手順書が渡し方を書く）
        inst["delegate"] = n["delegate"]
    if runner and n.get("engine_run"):
        plan_engine_run(b, nid, n, inst, engine_fallback)
    same = n.get("same_context_as")
    if same and isolated:
        die(f"{iid}: 遮断系（道具ゼロ）の役に same_context_as は使えない——前の節の文脈を持ち込むと、渡された物しか知らない読み手という遮断が崩れる（graph を直せ）")
    # 同じ役を続ける節: 前の節の instance の会話を続ける。engine が起こした会話なら session_id で --resume、
    # 回す側が Agent で起こした旧い盤面なら agent_id（SendMessage）。どちらも無ければ新しい会話になる旨を残す
    prior = next((i for i in b.rd["instances"].values() if i["node"] == same and i["status"] == "done"), None) if same else None
    if not runner:
        inst["deliver"] = deliver  # path: 役が自分で読む／paste: 本文を貼る。上限を決める前に 1 度だけ引いた物を使う
        if role_def_missing:
            inst["role_def_missing"] = role_def_missing
        if isolated:  # 道具ゼロ＝遮断系。Agent ツールでは CLAUDE.md を止められない
            inst["mode"] = "cli"
        if launchable and not (prior and prior.get("agent_id") and not prior.get("session_id")):
            spec = launch_spec(b, inst, role_def, resume_sid=(prior or {}).get("session_id"))
            if spec:
                inst["launch"] = spec
    if same:
        if prior and prior.get("session_id") and inst.get("launch"):
            inst["mode"] = "agent_continue"
            inst["continue_of"] = prior["id"]
            inst["session_id"] = prior["session_id"]
        elif prior and prior.get("agent_id"):
            inst["mode"] = "agent_continue"
            inst["continue_of"] = prior["id"]
            inst["agent_id"] = prior["agent_id"]
        else:
            inst["context_lost"] = (f"{same} の会話の番号（session_id）も agent id も無い（launch で起こしていないか、"
                                    "done に --agent-id を渡していない）。新しい会話で走る")
            b.state.setdefault("context_lost", []).append({"instance": iid, "round": b.round, "reason": inst["context_lost"]})
    if n["run_by"] in b.graph.get("tree_guard_roles", []):
        # 1 回の next の中では取り直さない（扇の節では項目数ぶん同じ写しを取っていた）——memo は盤面が持つ。
        snap = b.porcelain()
        if snap is None:
            die(f"{iid}: git status が取れない——{n['run_by']} の作業ツリー保護（前後の突合）ができない場所からは回せない（リポジトリの中で next を呼べ）")
        inst["tree_before"] = snap
    b.rd["instances"][iid] = inst
    b.trace("emit", instance=iid, sha=inst["prompt_sha"])
    return inst


def fan_items(b, nid):
    fo = b.nodes[nid]["fan_out"]
    fn = registry(b.rules, "FAN_OUT").get(fo["builtin"])
    if not fn:
        die(f"fan_out.builtin '{fo['builtin']}' が rules に無い")
    return fn(b, nid)


def run_driver_node(b, nid, n, notes):
    """機械の節（rules の BUILTINS）。decision を返す節は周の遷移を起こす。
    返り値: True = 進んだ / False = 止まった（notes に理由。人に聞く番の中断もこちら——
    呼び出し側は 2 つを同じに扱うので、三値にしない）"""
    fn = registry(b.rules, "BUILTINS").get(n["builtin"])
    if not fn:
        die(f"builtin '{n['builtin']}' が rules に無い")
    out = fn(b, nid)
    f = b.dir / "out" / f"r{b.round}" / (safe_name(nid) + ".json")
    write_json(f, out)
    b.state["outputs"][nid] = {"file": str(f.relative_to(b.dir)), "round": b.round}
    b.trace("builtin", node=nid, result=out)
    # 返りは 2 つの形のどちらか——{"ok": bool, "problems": [...]} か {"decision": ...}。
    # どちらでもない返りを合格に倒さない（`ok is False` だけを失敗にしていたとき、ok の無い返りが全部 done に載った）。
    if "decision" not in out:
        if not isinstance(out.get("ok"), bool):
            die(f"builtin '{n['builtin']}' の返りが {{'ok': 真偽値}} でも {{'decision': …}} でもない: {sorted(out)}")
        if not out["ok"]:
            notes.append(f"{nid}: " + "; ".join(out.get("problems", ["通らない"])))
            # **待ちに戻した節が在るなら、止まらずに先へ進める**（戻した節を同じ next で出す）。戻した節が今
            # 待ちになっていないのに rewound を名乗る返りは、同じ機械の節を回し続ける形なので落とす
            back = out.get("rewound") or []
            if not (isinstance(back, list) and all(isinstance(x, str) and x in b.nodes for x in back)):
                die(f"builtin '{n['builtin']}' の rewound は節の名前の一覧で返せ（{back!r}）——文字列を返すと 1 文字ずつ節と読まれる")
            if back:
                if any(b.node_state(x) != "pending" for x in back) or b.deps_ok(nid):
                    die(f"builtin '{n['builtin']}' が {back} を待ちに戻したと言うが、戻っていない（rules の欠陥）")
                b.trace("rewound", node=nid, nodes=back)
                return True
            return False
    def mark_done():
        b.rd["done"][nid] = {"at": now(), "builtin": n["builtin"]}
        b.state["done_ever"][nid] = b.round

    if "decision" not in out:
        mark_done()
        return True
    d = out["decision"]
    notes.append(f"{nid}: {d}——{out.get('reason', '')}")
    if d == "ask":
        # **諮る選択肢は engine が動ける語だけ。** 表が無かったとき、知らない語は答えられた瞬間に
        # 「続ける」側へ落ちて周が開いた——諮った意味が消える。立てる側で落とす（答える人を待たない）
        # 周の途中の問い（in_round）は周を動かさないので、使える語がさらに狭い（IN_ROUND_ACTIONS。答える側の cmd_answer と同じ表）
        can = IN_ROUND_ACTIONS if out["ask"].get("in_round") else ANSWER_ACTIONS
        unknown = [o for o in (out["ask"].get("options") or []) if o not in can]
        if unknown:
            die(f"{nid}: 人に聞く選択肢 {unknown} は engine が動けない語（動けるのは {list(can)}）")
    if d == "ask" and not b.state["unattended"]:
        # 人に聞く番——**done の印は付けない**（決着していない）。付けていたとき、次の next がこの節を再評価せず先へ
        # 進み、入口のガードで同じ報告を複製する必要が生じた。答えが stop なら cmd_answer が印を付け、continue なら周が変わる
        b.state["pending_human"] = {"node": nid, **out["ask"]}
        return False
    mark_done()
    if d == "next_round":
        if not open_next_round(b, nid):
            notes.append(f"{nid}: init --stop-after-round {b.state['stop_after_round']} の指定で、{b.round} 周目の締めの後に止めた（次の周は開かない）")
            return False
    elif d == "ask":  # 無人実行（有人は上で止めている）
        b.state["pending_human"] = {"node": nid, **out["ask"]}
        fn2 = hook(b.rules, "on_unattended")
        reason = fn2(b, b.state["pending_human"]) if fn2 else "無人実行: 諮る事態に当たったので保守的に停止"
        b.state.pop("pending_human")
        b.state["status"] = "stopped"
        notes.append(f"無人実行: 停止（{reason}）")
        if out["ask"].get("in_round"):
            # 周の途中の問いを無人で止めたら、後の節を出さない（出すと、答えの無い問いの先の工程が走る）
            b.state["halted"] = {"node": nid, "round": b.round, "by": "unattended", "reason": reason}
            return False
    elif d in TERMINAL_STATUS:
        b.state["status"] = d
    elif d != "continue":
        die(f"{nid}: decision '{d}' が不明")
    return True


def graph_changed(b, notes):
    """init の後に graph が編集されていたら、痕跡を残して知らせる（止めはしない——止めると直せない）。"""
    cur = sha(graph_text(b.state["graph"]))
    if cur != b.state.get("graph_sha"):
        b.state.setdefault("graph_changes", []).append({"round": b.round, "from": b.state.get("graph_sha"), "to": cur, "at": now()})
        b.state["graph_sha"] = cur
        b.trace("graph_changed", to=cur)
        notes.append(f"graph が init の後に変わっている（sha {cur}）。痕跡は process.graph_changes")


def engine_changed(b, notes):
    """**どの engine がこの周を回したか**を記録に残す（止めはしない——痕跡を残して知らせる）。

    graph は sha で追っているのに engine は誰も見ていなかった。盤面はリポジトリの中に在るので
    「対象を直しながら回す」形になるが、**回している engine はインストール済みの版**で、
    作業ツリーの直しは次にインストールするまで一度も走らない——そのため
    「新機構が実走で動いていない」という指摘が 3 周にわたって出続け、原因（engine が別物）に
    たどり着くのに 9 周かかった（実測 r10）。置き場と版を毎周書けば、記録を読むだけで分かる。
    """
    here = pathlib.Path(__file__).resolve().parent.parent          # <plugin>/engine/.. = <plugin>
    ver = ""
    try:
        ver = json.loads((here / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version", "")
    except (OSError, ValueError):
        ver = ""                                                    # 版が読めなくても置き場は残す
    cur = {"root": str(here), "version": ver}
    if cur != b.state.get("engine"):
        b.state.setdefault("engine_changes", []).append({"round": b.round, "from": b.state.get("engine"), "to": cur, "at": now()})
        b.state["engine"] = cur
        b.trace("engine_changed", root=cur["root"], version=cur["version"])
        notes.append(f"この周を回した engine: {cur['root']}（{cur['version'] or '版が読めない'}）"
                     "——レビュー対象の作業ツリーと別の置き場なら、作業ツリー側の直しはこの run では走っていない")


def frozen_outputs_stale(b, notes):
    """`once` の節の凍った出力を、**今の schema で測り直す**（止めはしない——痕跡を残して知らせる）。

    `once` の出力は最初に走った周で凍る。あとから schema に必須の欄を足しても、その節はもう走らないので
    **欄は永久に現れない**。欄を読む cond・述語は「無い＝偽」に倒れ、静かに、run の残り全周で偽のままになる。

    実測 2026-09-13: `p0.purpose` に `source_files` を 5 周目に足したが、この節は 1 周目で凍っていたので
    欄は現れず、それを読む `purpose_sources_changed` が 6 周とも偽だった。目的監査の走り直しが一度も
    起きず、**R2（独立設計との突合）が 6 周とも走らなかった**——この run が収束できない本当の理由がこれ。
    引き金・柵・述語が「自分が読む入力の存在を確かめずに入る」形の代表例で、**偽が正しい偽か、
    読めなかった偽かを、誰も区別していなかった**。

    **凍った出力が合っていたのは凍った時点の schema であって、今の schema ではない。** 周の頭で測り直す。
    節ごとに 1 度だけ言う（周ごとに繰り返すと notes が同じ行で埋まる）。
    """
    seen = {s["node"] for s in b.state.get("stale_frozen", [])}
    outs = None
    for nid, n in b.nodes.items():
        if nid in seen or not (n.get("once") and n.get("schema")) or nid not in b.state["done_ever"]:
            continue
        if outs is None:
            outs = b.outputs()
        if nid not in outs:
            continue
        errs = validate_schema(outs[nid], n["schema"])
        if not errs:
            continue
        b.state.setdefault("stale_frozen", []).append(
            {"node": nid, "round": b.round, "frozen_in": b.state["outputs"][nid]["round"],
             "errors": errs, "at": now()})
        b.trace("stale_frozen", node=nid, errors=len(errs))
        notes.append(f"{nid} は once で凍った出力（round {b.state['outputs'][nid]['round']}）が今の schema に合わない"
                     f"（{'; '.join(errs[:3])}）。**この欄を読む cond・述語は永久に偽になる**。痕跡は process.stale_frozen")


def open_next_round(b, nid):
    """次の周を開く唯一の口（周の締めの next_round と、人の答えの continue / escalate が呼ぶ）。
    init --stop-after-round N の run は、N 周目の締めの後で開かずに止める——偽を返し、盤面は stopped と halted
    （by=stop_after_round）になる。止めた後の next は halted の分岐が後の節を出さない。並べた run を 1 周で止めて
    合流させる運用と、プログラムが回す形のために、周の数を run の外が決める口（実測 2026-09-25: 止める口が無く、
    R の後の next 1 回で次の周の P1 まで開いた）"""
    n = b.state.get("stop_after_round")
    if n and b.round >= n:
        b.state["status"] = "stopped"
        b.state["halted"] = {"node": nid, "round": b.round, "by": "stop_after_round",
                             "reason": f"init --stop-after-round {n}: {b.round} 周目の締め（記録・収束の判定）の後で止めた——次の周は開いていない"}
        b.trace("halted", by="stop_after_round", round=b.round)
        return False
    b.new_round()
    fn = hook(b.rules, "on_new_round")
    if fn:
        fn(b)
    return True


def advance(b):
    """機械の節を走らせ、周の終わりなら次の周を開く。回す側に渡す節が出るまで（または止まるまで）進める。"""
    notes = []
    graph_changed(b, notes)
    engine_changed(b, notes)
    frozen_outputs_stale(b, notes)
    while True:
        progressed = False
        for nid, n in b.nodes.items():
            if b.node_state(nid) != "pending":
                continue
            node_deps = b.deps_ok(nid)
            # 扇の節は instance_deps が揃えば項目を先に出してよい（pipeline——全部の checker を待たない）。
            # cond / once は節の deps が揃ってから見る。active_in だけは先に見る
            early = (not node_deps and b.deps_met(nid)
                     and not (n.get("active_in") and b.state["thickness"] not in n["active_in"]))
            if not node_deps and not early:
                continue
            if node_deps:
                why = b.applicable(nid)
                if why:
                    b.rd["na"][nid] = why
                    progressed = True
                    continue
            if n["run_by"] == "driver":
                r = run_driver_node(b, nid, n, notes)
                if not r:  # 止まった（機械の節が通らない／人に聞く番）。二値——None の第 3 の値は持たない
                    return notes
                progressed = True
                continue
            if "fan_out" in n:
                items = fan_items(b, nid)
                if items or node_deps:
                    b.rd["item_counts"][nid] = len(items)  # いま分かっている項目の数（先出しの節は増えていく）
                mine = [i for i in b.rd["instances"].values() if i["node"] == nid]
                pending = [i for i in mine if i["status"] == "pending"]
                # 項目は正本（items/ のファイル）から読む——instance の item は欄を落とした写しで、
                # key を落とさない例外に支えて直読みしていると、写しの作り方を変えた周に静かに壊れる
                existing = {load_item(i, b.dir)["key"] for i in mine if i["status"] in ("pending", "done")}
                new_items = [it for it in items if it["key"] not in existing]
                for it in new_items:
                    emit_instance(b, nid, it)
                    progressed = True
                if node_deps and not new_items and not pending:
                    if mine:
                        b.rd["done"][nid] = {"at": now(), "instances": len(mine)}
                    else:
                        b.rd["empty"].append(nid)
                    b.state["done_ever"][nid] = b.round
                    progressed = True
                continue
            if not any(i["node"] == nid and i["status"] == "pending" for i in b.rd["instances"].values()):
                emit_instance(b, nid)
                progressed = True
        if not progressed:
            return notes
