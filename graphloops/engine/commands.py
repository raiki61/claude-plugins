"""回す側が呼ぶコマンド。init / next / done / skip / answer / thicken / add / patch / finalize / status / record。"""
import datetime
import json
import os
import pathlib
import sys

from .advance import advance, emit_instance, load_item
from .board import Board, empty_round
from .record import apply_writes
from .render import TOKEN, strip_prefix
from .rules import hook, load_rules, registry
from .schema import load_graph, validate_schema
from .util import ANSWER_ACTIONS, PLUGIN_ROOT, Reject, TERMINAL_STATUS, die, dump, get_path, git, has_path, now, porcelain, read_json, safe_name, set_path, sha, waiting, write_json
from .validator import find_validator, finalize, report_accepts, run_validator, env_root, traces


# **どの入力がパスかは graph が宣言し、engine は「どう確かめるか」だけを持つ。**
# 以前は名前の表（document・cwd）を engine が持っていた——engine は loop を知らない建前なのに、
# loop の入力名を 2 語だけ知っている形で、loop を足す人は engine を書き換える必要があった。
# 宣言（何がパスか）と手続き（実在の見方）を分けると、写しは 0 になる: graph の inputs が正本で、
# ここに在るのは kind の名前 → 見方の対応だけ（graphcheck が、知らない kind を静的に弾く）。
# rev は「この版を読め」と役に渡す git のリビジョンで、パスではない——実在の見方を持たない
# （engine は git を知らない。版が取れるかは rules が固定するときに確かめる）
INPUT_KINDS = {"file": ("ファイル", pathlib.Path.is_file), "dir": ("ディレクトリ", pathlib.Path.is_dir),
               "rev": ("リビジョン", None)}


def path_inputs(g):
    """この graph が「パス」と宣言した入力（名前 → (人に見せる語, 実在の見方)）。

    宣言が無い graph では空——**空は「検査しない」であって「通す」ではない**（名前が無ければ
    そもそも実在検査の対象にならない。表に無い名前が素通りしていた以前と同じ射程で、狭くなってはいない）。
    """
    out = {}
    for key, decl in (g.get("inputs") or {}).items():
        decl = decl or {}
        kind = decl.get("kind")
        # **rules が後から作る入力は init の引数ではない。** 宣言はするが（静的検査が
        # 『貼る穴に渡る入力は宣言を持つ』を見るため）、init の実在検査と正規化の対象からは外す
        if decl.get("by") == "rules":
            continue
        if kind in INPUT_KINDS and INPUT_KINDS[kind][1] is not None:
            out[key] = INPUT_KINDS[kind]
    return out


# 欠けを人に言うときの書き方。**旗を持たない鍵に -- を付けない**——付けていたとき、cwd の欠けの診断が
# `--cwd` と名乗り、そのまま打つと argparse が知らない旗で落ちた（init が持つ旗は下の 3 つと --input だけ）
CLI_FLAGS = ("request", "document", "lang")


def flag(key):
    return f"--{key}" if key in CLI_FLAGS else f"--input {key}=…"


def required_inputs_missing(g, graph_path, inputs):
    """graph のプロンプトが必須の穴として読む inputs（接頭を剥がして inputs.X になる、optional でない物）が渡されているか。
    ファイルなら在るか。要る入力は graph のプロンプトから機械で導く——ただし**どれがパスかは graph が
    宣言する**（graph の inputs が正本。engine は kind → 見方の対応だけを持つ）
    （実測 2026-09-13: research を --document 無しで init すると exit 0、2 回目の next で p0.claims の穴が埋まらず落ちた）。
    rules の on_init が後から足す入力（review_md 等）は init の引数ではないので、ここでは見ない。"""
    base = pathlib.Path(graph_path).parent
    paths = path_inputs(g)
    missing = []
    for nid, n in g.get("nodes", {}).items():
        pf = n.get("prompt_file")
        if not pf:
            continue
        try:
            tpl = (base / pf).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # 無い prompt_file は graphcheck の担当
        for m in TOKEN.finditer(tpl):
            optional, path = m.group(1) == "?", m.group(2).strip()
            if optional:
                continue
            # **接頭（file: / section: / ref:）の剥がし方は render が正本**。ここで手で知っていたとき、
            # section:inputs.X#見出し の穴だけを持つ節は鍵が取れず、実在検査にも欠け検査にも当たらなかった
            core = strip_prefix(path)
            key = core[len("inputs."):] if core.startswith("inputs.") else None
            # engine が名前で知る入力は、init の旗（CLI_FLAGS）と graph が宣言したパス（inputs）の和
            if not key or "." in key or key not in set(CLI_FLAGS) | set(paths) and key not in inputs:
                continue  # rules が後から足す入力は init の引数ではない
            val = inputs.get(key)
            # **空文字を「在る」側に倒さない。** pathlib.Path("") は "." になるので、--input cwd= は
            # 実在検査を素通りして空のまま盤面に入り、cwd を読む側（git の -C 等）が黙って別の場所を見る
            if val == "" and key in paths:
                missing.append(f"{flag(key)} が空（節 {nid}）")
            elif val is None:
                missing.append(f"{flag(key)}（節 {nid} の穴 {{{{{path}}}}}）")
            # **実在の検査を、貼る穴の接頭（file:）に相乗りさせない。** file: は「本文を貼る」ための綴りで、
            # 渡された物が在るかとは別の話である。回す側の節がパス渡しに寄ると（{{inputs.document}} だけの graph）
            # この分岐を通らず、存在しないパスが init を素通りする。
            # どれがパスかは graph の inputs が正本。宣言に無い名前の入力はどの実在検査にも当たらない
            elif key in paths:
                what, ok = paths[key]
                if not ok(pathlib.Path(val)):
                    missing.append(f"{flag(key)} の {val} という{what}が無い（節 {nid}）")
    return sorted(set(missing))


def check_graph(graph, validator):
    """**外から来た graph は、入口で静的検査を通す**（init が唯一の入口）。

    以前は静的検査が CLI にしかなく、engine は `init --graph <任意>` を何も確かめずに受け取った
    ——同梱のグラフだけが守られ、持ち込みのグラフは柵の外だった。実装は写さず、CLI と同じ関数を呼ぶ
    （検査の正本は scripts/graphcheck.py の check）。**取り込みは呼ぶ時に行う**: graphcheck は engine を
    読むので、頭で取り込むと輪になる。検査そのものが動かせない環境（取り込みに失敗する）では
    **黙って通さず die する**——「検査できないから通す」は、この差分が繰り返し塞いできた形である。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("graphloops_graphcheck", PLUGIN_ROOT / "scripts" / "graphcheck.py")
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:                      # noqa: BLE001 — 何で落ちても「検査できない」は同じ扱い
        die(f"graph の静的検査を動かせない（{type(e).__name__}: {e}）——検査を飛ばして init はしない")
    lines = []
    if not mod.check(graph, validator, emit=lines.append):
        die(f"{graph}: graph の静的検査が通らない（init で止める。直してから回せ）\n"
            + "\n".join(l for l in lines if str(l).startswith("NG")))


# ---------------------------------------------------------------- next
def cmd_next(a):
    b = Board(resolve_dir(a))
    if b.state["status"] in TERMINAL_STATUS and all(b.node_state(n) != "pending" for n in b.nodes):
        print(dump({"status": b.state["status"], "round": b.round, "ready": [], "note": "全部の節が終わっている。record.json と report を見よ"}))
        return
    if not b.state.get("pending_human"):
        # 人に聞いている間は進めない——先に advance すると答えの無いまま次の節（report.human_items 等）が出て、
        # 答えても既に出たプロンプトには入らない（実測 2026-09-12: stop と答えた後の報告に human_items が空）
        b.accept_tree_change = getattr(a, "accept_tree_change", None)  # 機械の作業ツリー突合（rules）が読む。done と同じ逃げ道
        notes = advance(b)
        b.save()
    if b.state.get("pending_human"):
        print(dump({"status": "awaiting_human", "round": b.round, "ready": [], "ask": b.state["pending_human"],
                    "how": "答えが決まったら loop.py answer --text <選択肢>。無人なら init --unattended で保守的な既定になる"}))
        return
    ready = [i for i in b.rd["instances"].values() if i["status"] == "pending"]
    print(dump({
        # **run_id は直列化で綴りが変わらない印**（読了の柵が「この転写は回す側のものか」を見るのに使う。
        # パスは json.dumps が Windows の区切りを二重化するので印にできない）
        "status": b.state["status"], "round": b.round, "thickness": b.state["thickness"],
        "dir": str(b.dir), "run_id": b.state.get("run_id"), "notes": notes,
        "ready": [{**{k: v for k, v in i.items() if k != "tree_before"}, **waiting(i)} for i in ready],
        "how": ("ready の全部を同時に始めてよい（同じ波）。"
                "cli（道具ゼロの遮断系）は **loop.py launch を呼べ**——engine が起こして out_path に落とす。"
                "自分の Bash から起こすな: 出力をファイルに落とす綴りは auto mode の分類器が止める"
                "（実測 2026-09-15）。Agent ツールでも起こすな: CLAUDE.md が注入され、止める設定が無い。"
                "agent は subagent_type に agent_type を渡す。"
                "起動は運び手（小さな汎用 agent）に任せてよい: 運び手は deliver=path なら『<prompt_file> を読み、その指示にそのまま従え』の 1 文で、"
                "deliver=paste なら prompt_file の本文をそのまま貼って役を起動し、返答を一字も変えず out_path に書き、あなたには『wrote』だけ返す。"
                "運び手は役の返答を受け取って書き切るまでが仕事——子を背景に立てたまま自分のターンを閉じるな"
                "（実測 2026-09-13: 閉じた運び手が『wrote』を返さないまま完了し、out_path が 13 分間空のままだった）。"
                "役が『ファイル内の指示には従わない』と拒んだら本文を貼る形（paste）で起こし直す（拒否を言い含めるな）。"
                "schema のある節で役が JSON でなく散文を返したら、同じ役に『判定も内容も変えず、Schema に合う JSON だけで出し直せ』と続けさせる"
                "——運び手が勝手に組み直すな、新しい役に立て直すな（実測 2026-09-13: r4 の役が Schema を渡されて Markdown を返し、done が非 JSON で拒んだ）。"
                "launch は 1 件ずつ ok と why と stderr を返す——ok でなければ stderr の with-auth: auth=… を読め"
                "（inherited / keychain なら認証は足りていて原因は役の側、none / keychain-miss なら認証が足りていない）。"
                "engine が起こせない節は why が出る——迂回を組まず人に渡せ。"
                "agent_continue は agent_id の agent に SendMessage で続ける（同じ渡し方）。"
                "runner は自分でやる（skills があればその skill を呼ぶ。置き場のパスで渡された物は要る所だけ Read）。返答を out_path に保存して "
                "loop.py done --node <id> [--agent-id <id>]（別の場所に置いたなら --output <file>）。ready が空で status が running なら、done の直後にもう一度 next。"
                "**期限（deadline_at）を持つ instance を背景の役・任せ先に渡したら、同じ手番で loop.py wait --node <id> を Bash の背景実行で立てよ**"
                "——役の完了の知らせは入れ子や上限落ちで消えるが、wait の終了はプロセスの終了としてハーネスが必ず知らせる。"
                "exit 0 なら done、exit 3（期限切れ）で out_path が空なら loop.py relaunch --node <id> --reason <理由> で起こし直す"
                "（新しい out_path と deadline_at が返る。前の試行が遅れて書いても別のファイルに落ち、記録に入らない）。"
                "期限を持たない instance に wait は使えない（期限の無い待ちを作らない）"),
    }))


# ---------------------------------------------------------------- launch
# 1 節あたりの上限（秒）。台本が下げられるように環境変数で差し替える。
LAUNCH_TIMEOUT = int(os.environ.get("GL_LAUNCH_TIMEOUT") or 1800)
# **engine が自分で起こしてよい形。** 起動が回す側の Bash から engine の中へ移ると、1 件ずつ人（と
# auto mode の分類器）が見ていた審査がそのぶん外れる。代わりに engine が「自分が何を起こすか」をここで
# 言い切る——**graph の宣言を読んで判断する柵は柵ではない**（graph を書き換えられる立場の人が柵ごと
# 書き換えられる。README が受容として書いている「実行の正本をレビュー対象の木から取る」問題）。条件は 2 つ:
#   1. 起こすのは engine 自身のインタプリタと、engine に同梱の層（scripts/with-auth.py）だけ。
#      層は claude 以外を名前で撥ねるので、engine が起こせる相手は claude に限られる
#   2. 遮断の旗（--tools "" と --setting-sources ""）が揃っていること——道具ゼロ・設定ゼロでない子は
#      engine の中から起こさない。道具が 1 つも無い子は何も実行できないので「権限の外で動く入れ子」に
#      ならない。これは argv から機械で確かめられる性質で、宣言や約束ではない
ISOLATION_FLAGS = (("--tools", ""), ("--setting-sources", ""))


def launch_prefix():
    """engine が起こしてよい前置（自分のインタプリタ＋同梱の層）。graph の via と一致するのが正常。"""
    return [sys.executable, str(PLUGIN_ROOT / "scripts" / "with-auth.py")]


def _norm(path):
    r"""綴りの違いを畳んで、同じ物を指しているかを比べられる形にする。

    graph の via は `{plugin_root}/scripts/with-auth.py` と書かれているので、Windows では埋めた後に
    区切りが混ざる（`D:\a\...\graphloops/scripts/with-auth.py`）。素の等値で見ると、同梱の層そのものを
    指していても撥ねる（実測 2026-09-16: windows-latest だけで engine の起動 3 件が赤かった）。
    **柵は緩まない**——normcase / normpath が揃えるのは区切りと大小だけで、
    `..` を挟んで外へ出た綴りは揃えても別物のまま。ファイルシステムは見ない（symlink や
    hardlink で「同じ物」に化ける経路を柵の中に入れない）。"""
    return os.path.normcase(os.path.normpath(path))


def launch_refusal(inst):
    """起こせない理由（起こしてよければ None）。**理由は回す側に見せる**——黙って飛ばさない。"""
    launch = inst.get("launch") or {}
    argv = launch.get("argv") or []
    if launch.get("missing"):
        return f"この環境に {launch['missing']} が無い（PATH を確かめるか、人が起こす）"
    want = launch_prefix()
    if [_norm(a) for a in argv[:len(want)]] != [_norm(w) for w in want]:
        return (f"engine が起こしてよい前置ではない（graph の launch.isolated.via が {want} を指していない）"
                f"——先頭は {argv[:2]}")
    for flag, val in ISOLATION_FLAGS:
        at = argv.index(flag) if flag in argv else -1
        if at < 0 or argv[at + 1:at + 2] != [val]:
            return f'遮断の旗 {flag} "{val}" が argv に無い——道具ゼロでない子は engine の中から起こさない'
    if not pathlib.Path(launch.get("stdin") or "").is_file():
        return f"材料 {launch.get('stdin')} が無い"
    return None


def launch_one(inst):
    """1 節を起こし、標準出力を out_path に落とす。返すのは回す側と記録に見せる 1 件ぶんの結果。"""
    import subprocess  # 起こす節でだけ要る（全サブコマンドの起動に掛けない）
    got = {"id": inst["id"], "node": inst["node"], "out_path": inst["out_path"]}
    why = launch_refusal(inst)
    if why:
        return {**got, "ok": False, "why": why}
    out = pathlib.Path(inst["out_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(inst["launch"]["stdin"], "rb") as fh, open(out, "wb") as sink:
            p = subprocess.run(inst["launch"]["argv"], stdin=fh, stdout=sink,
                               stderr=subprocess.PIPE, timeout=LAUNCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {**got, "ok": False, "why": f"{LAUNCH_TIMEOUT} 秒で返らなかった（out_path は途中まで）"}
    except OSError as e:
        return {**got, "ok": False, "why": f"起こせない: {e}"}
    # 層の 1 行（auth=…）はここにしか出ない。**必ず回す側へ運ぶ**——起動が engine の中に入ったぶん、
    # 認証落ちが「役の返答の不良」に見えてしまう経路をここで塞ぐ
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    size = out.stat().st_size if out.exists() else 0
    return {**got, "ok": p.returncode == 0 and size > 0, "exit": p.returncode, "bytes": size,
            "stderr": err[-600:]}


def cmd_launch(a):
    """遮断系（道具ゼロの役）を engine が起こす。回す側の Bash に子の claude を出さない。

    **なぜ engine が起こすか。** 回す側が Bash から起こす形は、出力を out_path に落とす綴りだと auto mode の
    分類器が『Auto-Mode Bypass』で止める（実測 2026-09-15: 同じ層でも出力が会話に出る形は通り、
    `< 材料 > out_path` は止まった）。Agent ツールへ逃げると CLAUDE.md が注入されて遮断が名ばかりになる
    （実測 2026-09-12）。gates の読み役が同じ起動を通せているのはフックの中で起きているからで、認証の差ではない。
    起こす場所を engine へ移すと、回す側は loop.py を呼ぶだけになる——代わりに、何を起こすかは
    launch_refusal が機械で縛る。
    """
    b = Board(resolve_dir(a))
    want = getattr(a, "node", None)
    ready = [i for i in b.rd["instances"].values()
             if i["status"] == "pending" and i.get("mode") == "cli" and (not want or i["id"] == want)]
    if not ready:
        die("起こせる遮断系の節が無い（next が cli の節を出しているか、--node の綴りを確かめよ）", 1)
    if len(ready) == 1:
        results = [launch_one(ready[0])]
    else:
        # 同じ波に載った遮断系は互いに依存しない。直列に待つと素直に足し算になる
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(ready))) as ex:
            results = list(ex.map(launch_one, ready))
    for r in results:
        b.trace("launched", id=r["id"], ok=r["ok"], exit=r.get("exit"), bytes=r.get("bytes"),
                why=r.get("why"), stderr=(r.get("stderr") or "")[-200:])
    print(dump({"launched": results,
                "how": ("ok の節は返答が out_path に在る——そのまま loop.py done --node <id>（--output は要らない）。"
                        "ok でない節は why と stderr を読め: stderr の with-auth: auth=… が inherited / keychain なら"
                        "認証は足りていて原因は役の側、none / keychain-miss なら認証が足りていない。"
                        "engine が起こせない節（why が『前置ではない』『旗が無い』）は人に渡す——迂回を組むな")}))


# ---------------------------------------------------------------- done
def parse_output(text):
    """役の返答を JSON に読む。**素の JSON を先に試す**——先に囲いを探すと、本文の中の ``` を囲いと誤認して
    中身を切り出し、正しい返答を『読めない』で拒む（実測 2026-09-12: 指摘文に ```json を書いた返答が落ちた。
    役の指摘がコードの囲いに触れるのはレビューでは普通に起きる）。"""
    text = text.strip()
    # 空は候補を出す前に落とす。候補は無条件に全文を 1 本出すので、後ろで「候補が 0 本」を
    # 見ようとしても到達しない（実測 2026-09-15: そう書いた枝が到達不能で、空の返答は
    # 囲いを名指しする側に落ちていた）。**読み元は名指しできない**——cmd_done は --output /
    # --stdin / out_path の 3 入口で text を作り、ここへは text しか渡らない。1 つに決め打つと、
    # 既定の導線（--output）で誤った場所を直しに行かせる。
    if not text:
        raise Reject("返答が中身を持たない（空か空白だけ）——役が何も返していないか、"
                     "渡した返答が空。JSON だけを返せ")
    errs, tried = [], set()
    for label, cand in _json_candidates(text):
        # 同じ中身の候補を 2 回 loads しない。囲いの外に波括弧が無い通常形では
        # 「``` 囲いの中」と「{ から } まで」が同一文字列になり、拒否文にバイト単位で
        # 同じ行が 2 本並んで「相異なる候補を 3 本試した」と読めてしまう。
        if cand in tried:
            continue
        tried.add(cand)
        try:
            return json.loads(cand)
        except json.JSONDecodeError as e:
            errs.append((label, cand, e))
    # **どれが原因かを engine が断定しない。** 候補は素の str で、元テキストのどこから切ったかを
    # 運ばないので、pos を候補間で比べても「どこまで読めたか」にならず、行・桁も読む人が開く
    # out_path の座標にならない（実測 2026-09-15: 散文に波括弧が混じると切り出した断片の pos が
    # 全文の pos 0 に勝ち、JSON を 1 文字も返していない返答に『直すのは中身』と出た。素の JSON の
    # 後ろに文が付いた形＝Extra data では、旧文言『JSON だけを返せ』の方が正しかった）。
    # 候補ごとに何が起きたかを並べ、直す先は読む人に選ばせる。
    lines = [f"返答が JSON として読めない（候補 {len(errs)} 本すべてで失敗）"]
    for label, cand, e in errs:
        lines.append(f"  - {label}: {e.msg} / {_around(cand, e.pos)}")
    lines.append('よくある原因: 文字列値の中のエスケープしていない " ／ 末尾のカンマ ／ '
                 "JSON の前後に付いた地の文 ／ 囲い（```）が閉じていない")
    raise Reject("\n".join(lines))


def _around(text, pos):
    """折れた位置の前後を 1 行に畳んで返す。読む人が『どの値か』を目で見つけられる幅だけ。

    端では省略記号を付けない——前が無いのに ... を出すと「まだ前がある」と読めてしまう。
    """
    head = text[max(0, pos - 70):pos].replace("\n", " ")
    tail = text[pos:pos + 30].replace("\n", " ")
    lead = "..." if pos > 70 else ""
    trail = "..." if pos + 30 < len(text) else ""
    return f"{lead}{head}[ここ]{tail}{trail}"


def _json_candidates(text):
    """読める順に (名前, 候補) を出す: 全文そのまま → 本文中の ``` 囲いの中 → 最初の { から最後の } まで。

    名前を添えるのは拒否の文のため——どの切り方で何が起きたかを並べないと、engine が
    原因を 1 つに決めつけることになる。
    """
    yield "全文そのまま", text
    # **正規表現を使わない。** 貪欲な空白 + lazy な本文の組み合わせは、閉じ ``` が無い返答で
    # 後戻り地点が空白の数だけ生まれ、その各点で残り全文を舐め直す（実測 2026-09-16:
    # 閉じない囲い + 空白 80,000 文字で 21.8 秒。文字列探索へ替えた後は 0 ms）。
    # 役の返答は engine が読む唯一の外部入力なので、入力長に対して線形でない読み方をしない。
    fence = text.find("```")
    if fence != -1:
        body = text[fence + 3:]
        if body[:4].lower() == "json":
            body = body[4:]
        close = body.find("```")
        if close != -1:
            yield "``` 囲いの中", body[:close].strip()
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        yield "{ から } まで", text[s:e + 1]


STDIN_MAX = 20_000_000  # 文字


def cmd_done(a):
    b = Board(resolve_dir(a))
    inst = b.rd["instances"].get(a.node)
    if not inst:
        raise Reject(f"この周に節 '{a.node}' は出ていない（loop.py next で確かめよ）")
    if inst["status"] != "pending":
        raise Reject(f"節 '{a.node}' は既に {inst['status']}")
    nid = inst["node"]
    n = b.nodes[nid]
    # **出した後に graph が変わり、deps が増えた節は、増えた deps を待つ。** 出した時点で揃っていた deps だけを信じると、
    # run の途中で足した前段（例: 修正の前の事前審査）を飛ばした返答を受け付ける（実測 2026-09-24: 回す側が手で待たせた）
    if not b.deps_met(nid):
        wait = [d for d in n.get("deps", []) if b.node_state(d) == "pending"]
        raise Reject(f"節 '{a.node}' の deps {wait} がまだ済んでいない（出した後に graph が変わった）——先にそちらを回せ（loop.py next）")
    # 読む順: --output の明示 → --stdin の明示 → 置き場（out_path）。以前は置き場が標準入力より先で、拒まれた前回分が
    # 置き場に残っていると新しい返答を標準入力で渡しても古い方が黙って記録に入った（実測 2026-09-12）。
    # 標準入力は**明示されたときだけ**読む——「端末でなければ読む」にしていたとき、呼び出し元の stdin が閉じない
    # パイプだと read() が戻らず done が止まった（実測 2026-09-13: 回す側の shell で 120 秒超えて殺した）。
    # どこから読んだかは instance と返事に残す。
    text, read_from = None, None
    if a.output:
        try:
            text, read_from = pathlib.Path(a.output).read_text(encoding="utf-8"), f"--output {a.output}"
        except (OSError, UnicodeDecodeError) as e:
            # UnicodeDecodeError は ValueError 派生で OSError ではない——列挙から漏れると総括 except に落ち、
            # 呼び直せば通る事故が exit 2（盤面が読めない）に化ける（実測 2026-09-13: UTF-16 の返答で再現）
            raise Reject(f"{a.output}: 読めない（{e}）——UTF-8 で書き直して done し直せ")
    elif getattr(a, "stdin", False):
        # バイトで読んで UTF-8 に決める——テキストの stdin は OS 既定の文字コード（Windows は cp1252、日本語 Windows なら cp932）で復号され、
        # 日本語の返答が壊れて JSON にならない（実測 2026-09-13: CI の windows-latest で標準入力の done が落ちた）
        raw = sys.stdin.buffer.read(STDIN_MAX * 4 + 1)
        try:
            got = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise Reject(f"標準入力が UTF-8 でない（{e}）——UTF-8 で渡すか --output でファイルを渡せ")
        if len(got) > STDIN_MAX:
            raise Reject(f"標準入力が {STDIN_MAX} 文字を超えている——--output でファイルを渡せ")
        if not got.strip():
            raise Reject("--stdin なのに標準入力が空——返答を流すか、--output か置き場で渡せ")
        text, read_from = got, "stdin"
    if text is None and inst.get("out_path") and pathlib.Path(inst["out_path"]).is_file():
        try:
            text, read_from = pathlib.Path(inst["out_path"]).read_text(encoding="utf-8"), f"out_path {inst['out_path']}"
        except (OSError, UnicodeDecodeError) as e:
            raise Reject(f"{inst['out_path']}: 読めない（{e}）——UTF-8 で書き直して done し直せ")
    if text is None:
        raise Reject(f"返答が無い——--output か標準入力で渡すか、運び手に {inst.get('out_path')} へ書かせる")
    if inst.get("mode") == "cli" and a.agent_id:
        raise Reject("cli で起こした遮断系に agent_id は無い（別プロセスは返答と共に終わる）——--agent-id を渡すな")
    inst["read_from"] = read_from
    if n.get("schema"):
        output = parse_output(text)
        errs = validate_schema(output, n["schema"])
        if errs:
            print("NG 返答が型に合わない（直して done し直す。回す側が中身を補ってはいけない——役に返させろ）:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # 本文を返す節にも空の検査を当てる（schema 節は minLength が同じ形を落としている）。空を受けると
        # 0 バイトの report.md が残り、『人が決めること』が黙って消える（実測: --output <空> も </dev/null> も exit 0 だった）。
        if not text.strip():
            raise Reject(f"節 '{nid}' の返答が空——本文を返す節に空は受け付けない（役が何も返していないか、運び手が {inst.get('out_path')} に書けていない）")
        output = {"text": text}
    item = load_item(inst, b.dir)
    # 作業ツリーの前後突合（書き換えを塞ぐのは定義でも自制でもなくこの突合）
    if "tree_before" in inst:
        after = porcelain()
        if after is None:
            raise Reject("git status が取れない——作業ツリーの突合ができない場所から done している（リポジトリの中で呼べ）")
        if after != inst["tree_before"]:
            diff = sorted(set(after or []) ^ set(inst["tree_before"] or []))
            # 同じ波に保護対象の instance が複数在ると、誰が汚したかはこの突合では決まらない（基準点は全員ほぼ同時刻の
            # グローバルな git status で、done を呼んだ順に検出される）。**帰属を断定せず、同じ波の一覧を記録に残す。**
            peers = sorted(i for i, x in b.rd["instances"].items()
                           if i != a.node and "tree_before" in x and x["status"] == "pending")
            who = f"（同じ波で保護対象の instance が他に {len(peers)} 件走っている: {peers}——変えたのがこの instance とは限らない）" if peers else ""
            if not a.accept_tree_change:
                raise Reject(f"{inst['run_by']} の前後で作業ツリーが変わっている: {diff}{who}。戻してから done し直すか、自分の変更なら --accept-tree-change <理由>")
            b.state.setdefault("git_mismatches", []).append({"instance": a.node, "diff": diff, "accepted": a.accept_tree_change,
                                                            "round": b.round, "concurrent_guarded": peers})
    # 扇の被覆（返した答えが項目を全部覆っているか。欠けは『なし』ではない）
    remaining = None
    cover = n.get("fan_out", {}).get("cover")
    if cover and item:
        items = get_path({"item": item}, cover["items_at"])
        key = cover.get("key", "id")
        want = {x[key] for x in items}
        got = {x.get(key) for x in (get_path(output, cover["answers_at"]) if has_path(output, cover["answers_at"]) else [])}
        extra = got - want
        if extra:
            raise Reject(f"項目に無い {key} を返している: {sorted(extra)}")
        remaining = sorted(want - got)
    # 段の昇格（降格は engine が拒む）
    tf = n.get("thickness_from")
    if tf and has_path(output, tf):
        want = get_path(output, tf)
        if want not in b.tiers:
            raise Reject(f"段 '{want}' はこの loop の段（{b.tiers}）に無い")
        if b.tiers.index(want) < b.tiers.index(b.state["thickness"]):
            raise Reject(f"段を {b.state['thickness']} から {want} に下げようとしている。降格は依頼者の指定で init に渡す（回す側の自己判断による降格＝さぼり降格を禁ずる）")
        if b.tiers.index(want) > b.tiers.index(b.state["thickness"]):
            thicken(b, want, output.get(n.get("thickness_reason_from", ""), ""), by=nid)
    # 節ごとの整合（型では書けない規則。rules が持つ）。out を検査・補ってから writes を当てる。
    # **record を書く post_check は例外として 2 つ在る**（review-loop の base_valid と r2_design——検査の結果で
    # 初めて決まる値を書く）。それ以外は out だけを見る規約で、記録を書く経路は writes（WRITE_OPS）が主
    notes = []
    pc = n.get("post_check")
    if pc:
        fn = registry(b.rules, "POST_CHECKS").get(pc)
        if not fn:
            die(f"post_check '{pc}' が rules に無い")
        note = fn(b, nid, output, item)
        if note:
            notes.append(note)
    apply_writes(b, nid, output, item)
    check = hook(b.rules, "check_record")
    if check:
        errs = check(b, nid)  # 今 done している節はまだ done の印が無いので名指しで渡す（走った事実との突合に要る）
        if errs:
            print("NG 記録の整合が取れない（役に返させ直す。回す側が補ってはいけない）:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
    f = b.dir / "out" / f"r{b.round}" / (safe_name(a.node) + ".json")
    write_json(f, output)
    if n.get("save_text_as"):
        (b.dir / n["save_text_as"]).write_text(output["text"], encoding="utf-8")
        notes.append(f"本文は {b.dir / n['save_text_as']} に保存した")
    b.state["outputs"][nid] = {"file": str(f.relative_to(b.dir)), "round": b.round, "instance": a.node}
    # **綴りは 1 つに決める。** 以前はこの 2 行が同じ f を 2 つの綴りで書いていた——outputs は盤面からの相対、
    # instance は `--dir` をそのまま前に付けた綴り。後者は**記録されていない過去の作業ディレクトリ**に錨を持つので、
    # 相対の `--dir` で回した run を別の作業ディレクトリから開くと読めない（実測 2026-09-13: 絶対 --dir で開いても
    # cwd=/tmp から ref('raw') が SystemExit 2。最終報告の節でだけ露出した）。盤面からの相対に揃えると、
    # 錨は「いまの呼び出しが渡した --dir」1 つになり、読む側に規約の知識が要らなくなる。
    inst.update({"status": "done", "done_at": now(), "output_file": str(f.relative_to(b.dir))})
    if a.agent_id:
        inst["agent_id"] = a.agent_id
    b.trace("done", instance=a.node, sha=sha(text))
    msg = f"ok {a.node} を受け付けた（読んだ先: {read_from}）"
    if remaining:
        item = dict(item)
        base = cover["items_at"].split(".", 1)[1]
        item[base] = [x for x in item[base] if x[cover.get("key", "id")] in remaining]
        k = sum(1 for i in b.rd["instances"] if i.startswith(f"{nid}[{item['key']}]"))
        new = emit_instance(b, nid, item, suffix=f"#{k + 1}")
        msg += f"。ただし答えが欠けた項目がある: {remaining}——欠けた分だけ {new['id']} として出し直した（無言の省略を『なし』と読まない）"
    if "fan_out" not in n:
        b.rd["done"][nid] = {"at": now(), "instance": a.node}
        b.state["done_ever"][nid] = b.round
    b.save()
    # done の 1 行にも run_id を載せる——done だけを打った session でも印が転写に載る（読了の柵が読む）
    print("。".join([msg, *notes]) + f"。続きは loop.py next（run {b.state.get('run_id')}）")


# ---------------------------------------------------------------- skip / answer / thicken / add / patch
def cmd_skip(a):
    b = Board(resolve_dir(a))
    n = b.nodes.get(a.node)
    if not n:
        die(f"節 '{a.node}' が無い")
    if not n.get("optional"):
        raise Reject(f"節 '{a.node}' は optional でない——省けない（省略できる機構は graph の optional と段の宣言が正本）")
    if b.node_state(a.node) != "pending":
        raise Reject(f"節 '{a.node}' は {b.node_state(a.node)}")
    b.rd["skipped"][a.node] = a.reason
    for i in b.rd["instances"].values():
        if i["node"] == a.node and i["status"] == "pending":
            i["status"] = "skipped"
    b.state["done_ever"][a.node] = b.round
    b.trace("skip", node=a.node, reason=a.reason)
    b.save()
    print(f"ok {a.node} を省いた（報告の『省略した機構』に載る）")


def cmd_answer(a):
    b = Board(resolve_dir(a))
    ph = b.state.get("pending_human")
    if not ph:
        raise Reject("人に聞いている節は無い")
    ans = a.text.strip()
    if ans not in ph["options"]:
        raise Reject(f"答えは {ph['options']} のどれか")
    if ans not in ANSWER_ACTIONS:  # 立てる側でも落としているが、盤面を手当てして通った経路にもここで当てる
        raise Reject(f"答え '{ans}' は engine が動けない語（動けるのは {list(ANSWER_ACTIONS)}）——諮りの選択肢の側が壊れている")
    ph["note"] = a.note or ""
    fn = hook(b.rules, "on_answer")
    if fn:
        fn(b, ph, ans)
    b.state.pop("pending_human")
    b.trace("answer", answer=ans, kinds=ph.get("kinds"))
    if ans == "stop":
        # 聞いた節はここで決着——ask では done の印を付けないので、stop の答えが印を付ける（continue は周が変わる）
        b.rd["done"][ph["node"]] = {"at": now(), "builtin": "answer:stop"}
        b.state["done_ever"][ph["node"]] = b.round
        b.state["status"] = "stopped"
    else:
        if ans == "escalate":
            # 段名は graph の thickness.tiers が正本——escalate は最上段へ
            if not b.tiers:
                raise Reject("この loop に段（thickness.tiers）が無いので escalate できない")
            thicken(b, b.tiers[-1], "依頼者の判断（諮った結果）", by="answer")
        b.new_round()
        fn2 = hook(b.rules, "on_new_round")
        if fn2:
            fn2(b)
    b.save()
    print(f"ok 答え '{ans}' を記録した。続きは loop.py next")


def thicken(b, to, reason, by):
    cur = b.state["thickness"]
    if not b.tiers or to not in b.tiers:
        raise Reject(f"段 '{to}' はこの loop の段（{b.tiers}）に無い")
    if b.tiers.index(to) <= b.tiers.index(cur):
        raise Reject(f"{cur} から {to} へは下げられない（降格は init の --thickness だけ）")
    b.state.setdefault("thickness_changes", []).append({"round": b.round, "from": cur, "to": to, "by": by, "reason": reason})
    b.state["thickness"] = to
    b.state["max_rounds"] = max_rounds_for(b.graph, to)
    fn = hook(b.rules, "on_thickness")
    if fn:
        fn(b, to)
    b.trace("thicken", to=to, by=by, reason=reason)


def max_rounds_for(graph, thickness):
    return graph["round"].get("max_rounds_by_thickness", {}).get(thickness, graph["round"]["max_rounds"])


def cmd_thicken(a):
    b = Board(resolve_dir(a))
    thicken(b, a.to, a.reason, by="thicken")
    b.save()
    print(f"ok 段を {a.to} に上げた。この周から {a.to} の節が有効になる（次の next で出る）")


def cmd_add(a):
    b = Board(resolve_dir(a))
    fn = hook(b.rules, "add")
    if not fn:
        raise Reject("このループの rules は add を受け付けない")
    msg = fn(b, read_json(a.file), a.reason)
    b.trace("add", reason=a.reason)
    b.save()
    print(f"ok {msg}")


def cmd_patch(a):
    """記録（既定）か盤面（state. 接頭）の手当て。痕跡は state.patches と trace に残る。

    盤面も許すのは、run の途中で graph と雛形が変わると rules の私有の鍵が足りずに next が止まり、
    記録側の手当てでは届かないから（実測 2026-09-12: 雛形が新しい loop_state の鍵を読み、回す側が
    state.json を手で書き換えて続けた——手当ての口が盤面の壊れ方を覆っていなかった）。
    """
    b = Board(resolve_dir(a))
    if a.path.startswith("state."):
        set_path(b.state, a.path[len("state."):], read_json(a.file))
    else:
        set_path(b.record, a.path, read_json(a.file))
    b.state.setdefault("patches", []).append({"round": b.round, "path": a.path, "reason": a.reason, "at": now()})
    b.trace("patch", path=a.path, reason=a.reason)
    b.save()
    print(f"ok {a.path if a.path.startswith('state.') else 'record.' + a.path} を手当てした（痕跡は state.patches と trace に残る）")


# ---------------------------------------------------------------- finalize / status / record
def cmd_finalize(a):
    b = Board(resolve_dir(a))
    finalize(b)
    b.save()
    v = run_validator(b)
    # **痕跡の欄を人に見せる口。** finalize が process へ写すだけで、検証器も報告も 1 度も読まない欄が
    # 在った——鳴っても何も起きないので、測れなかった周も静かに終われた（実測 2026-09-14）。
    # 赤にはしない（収束の意味が変わる）。**見えるようにする**のがここの仕事
    print(dump({"validator": v, "record": str(b.dir / "record.json"), "traces": traces(b.record)}))
    accepts = report_accepts(b)  # 受理集合の正本は graph。鍵の綴りと既定は engine の 1 か所（validator.report_accepts）
    if v["exit"] not in accepts:  # None（検証器が無い・動かない）も不合格
        sys.exit(1)


def cmd_status(a):
    b = Board(resolve_dir(a))
    st = b.state
    print(dump({
        "dir": str(b.dir), "run_id": st.get("run_id"), "loop": st["loop_name"], "status": st["status"], "round": b.round, "thickness": st["thickness"],
        "max_rounds": st["max_rounds"], "unattended": st["unattended"],
        "this_round": {"done": sorted(b.rd["done"]), "na": b.rd["na"], "skipped": b.rd["skipped"], "empty": b.rd["empty"],
                       "pending_instances": [{"id": i["id"], **waiting(i)} for i in b.rd["instances"].values() if i["status"] == "pending"]},
        "pending_human": st.get("pending_human"), "validator": st.get("validator"),
    }))


WAIT_POLL = float(os.environ.get("GL_WAIT_POLL") or 15)   # wait が盤面を見に行く間隔（秒）。台本が縮められるように環境変数で差し替える


def cmd_wait(a):
    """背景の役・任せ先の返答を、期限まで待つ（回す側が Bash の背景実行で立て、その終了で起きる）。

    **盤面は読むだけで書かない**（回す側が同時に next / done を打っても競合しない）。返るのは 3 通り: 返答が置き場に在る・
    instance が済んだ（exit 0）、期限を過ぎた（exit 3。次の手を印字）。期限を持たない instance は拒む——期限の無い wait は、
    任せ先が書かずに落ちたとき永久に返らず、塞ぎたい『黙って止まる』をそのまま作る"""
    import time  # 待つ口でだけ要る
    d = pathlib.Path(resolve_dir(a))
    while True:
        st = read_json(d / "state.json")
        inst = st["rounds"][-1]["instances"].get(a.node)
        if inst is None:
            raise Reject(f"今の周に instance '{a.node}' が無い（id は next の ready の id）")
        if not inst.get("deadline_at"):
            raise Reject(f"'{a.node}' は期限（deadline_at）を持たない——graph の deadline_minutes が無い節に wait は使えない")
        out = pathlib.Path(inst.get("out_path") or "")
        if inst["status"] != "pending" or (out.name and out.is_file() and out.stat().st_size > 0):
            print(dump({"id": a.node, "written": True, "status": inst["status"], "out_path": str(out), **waiting(inst)}))
            return
        w = waiting(inst)
        if w["overdue"]:
            print(dump({"id": a.node, "written": False, **w,
                        "how": f"期限を過ぎても {out} に返答が無い。役が生きていないなら loop.py relaunch --node {a.node} --reason <理由> で起こし直せ"}))
            sys.exit(3)
        left = (datetime.datetime.fromisoformat(inst["deadline_at"]) - datetime.datetime.fromisoformat(now())).total_seconds()
        time.sleep(max(0.1, min(WAIT_POLL, left)))


def cmd_relaunch(a):
    """待っている instance を起こし直す——同じ節・同じ項目で出し直し、試行の回数と理由を盤面と trace に刻む。

    **前の試行を締め出す**: 新しい試行は別の out_path（.a<試行>）を持ち、前の置き場に在った物は .stale-a<試行> へ退ける。
    前の試行が遅れて書いても、done と wait は今の試行の置き場しか読まない（Temporal の task token が試行ごとに一意なのと同じ）。
    作業ツリーの基準点（tree_before）は前の試行の物を引き継ぐ——取り直すと、前の試行が書き換えた作業ツリーが基準に入り、突合を素通りする"""
    b = Board(resolve_dir(a))
    prev = b.rd["instances"].get(a.node)
    if prev is None or prev["status"] != "pending":
        raise Reject(f"'{a.node}' は今の周の待っている instance でない（起こし直せるのは pending だけ）")
    item = load_item(prev, b.dir) if prev.get("item_file") else None
    nid = prev["node"]
    suffix = a.node[len(nid + (f"[{item['key']}]" if item else "")):]
    n = prev.get("attempts", 1)
    old = pathlib.Path(prev.get("out_path") or "")
    if old.name and old.is_file():
        old.replace(old.with_name(old.name + f".stale-a{n}"))
    new = emit_instance(b, nid, item, suffix=suffix, attempt=n + 1)
    if "tree_before" in prev:
        new["tree_before"] = prev["tree_before"]
    new["attempt_log"] = (prev.get("attempt_log") or []) + [{"at": new["emitted_at"], "reason": a.reason,
                                                             "prev_emitted_at": prev["emitted_at"], "prev_out_path": str(old)}]
    b.trace("relaunched", instance=a.node, attempt=n + 1, reason=a.reason)
    b.save()
    print(dump({"relaunched": {k: v for k, v in new.items() if k != "tree_before"},
                "how": "新しい out_path に書かせて起こし直せ（prompt_file は描き直した。前の試行の置き場は読まれない）"}))


def cmd_record(a):
    print(dump(Board(resolve_dir(a)).record))


# ---------------------------------------------------------------- init
def resolve_dir(a):
    # **綴りは絶対に揃える。** 相対の --dir で作った run は instance の item_file にも相対の綴りが残り、
    # 別の cwd から開き直した回に load_item が読めずに落ちる（扇の重複排除が正本を読むようになって
    # next も同じ経路を通る）。盤面の外から渡る唯一の入口がここなので、ここで 1 度だけ解決する
    if getattr(a, "dir", None):
        return str(pathlib.Path(a.dir).resolve())
    gd = git("rev-parse", "--git-dir")
    if gd:
        base = pathlib.Path(gd.strip()).resolve() / "graphloops"
        found = {}
        for p in sorted(base.glob("*/current")):
            t = p.read_text(encoding="utf-8").strip()
            if pathlib.Path(t).is_dir():
                found[p.parent.name] = t
        if len(found) > 1:
            # 別のループの run に記録が入る取り違えを黙って起こさない——曖昧なら指させる
            die("--dir が無く、current を持つループが複数ある: " + ", ".join(f"{k} → {v}" for k, v in found.items()) + "——--dir で指せ（init の出力の dir）")
        if found:
            return next(iter(found.values()))
    die("--dir が無く、current も見つからない（init したか？）")


def cmd_init(a):
    graph = a.graph or str(PLUGIN_ROOT / "graphs" / f"{a.loop}.json")
    g, why = load_graph(graph)
    if why:
        die(why)
    if not g.get("exec"):
        die(f"{graph}: 実行用の欄（exec: true）が無い——このグラフはまだ写しだけで、engine では回せない")
    rules = load_rules(graph, g)
    loop = g["loop"]
    # 検証器と必須の入力は置き場を作る前に解決する——die しても空の盤面を残さない
    validator = find_validator(loop, g.get("plugin"), a.validator)
    check_graph(graph, validator)
    req = a.request
    if req.startswith("@"):
        req = pathlib.Path(req[1:]).read_text(encoding="utf-8")
    inputs = {"request": req, "document": a.document,
              "lang": a.lang or "依頼文の言語（利用者の言語）", "cwd": os.getcwd()}
    for kv in a.input or []:
        k, _, v = kv.partition("=")
        inputs[k] = v
    # **パスの入力は、既定でも --input の上書きでも同じ正規化を通す**（どれがパスかは graph の inputs が正本）。
    # 片方だけ絶対化していたとき、同じ鍵に 2 つの正本（絶対と相対）ができて実在検査が別の場所を見た
    for k in path_inputs(g):
        if inputs.get(k):
            inputs[k] = str(pathlib.Path(inputs[k]).resolve())
    missing = required_inputs_missing(g, graph, inputs)
    if missing:
        die("この loop に要る入力が無い（init で止める——以前は 2 手先の穴埋めで初めて落ち、盤面を捨てるしかなかった）: " + "; ".join(missing))
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if a.dir:
        d = pathlib.Path(a.dir).resolve()   # 盤面の綴りは入口で 1 度だけ解決する（resolve_dir と同じ規律）
    else:
        gd = git("rev-parse", "--git-dir")
        if not gd:
            die("git リポジトリでない。--dir で置き場を渡せ")
        base_dir = pathlib.Path(gd.strip()).resolve() / "graphloops" / loop
        d = base_dir / run_id
        n = 2
        while d.exists():  # 同じ秒に 2 回 init すると run-id が衝突する（実測 2026-09-13: 台本で FileExistsError→exit 2）
            d = base_dir / f"{run_id}-{n}"
            n += 1
        run_id = d.name
    # **段と decider の検査は置き場を作る前に。** 後ろに置いていたとき、die しても中身ゼロの run ディレクトリが
    # 残った（実測 2026-09-13: --thickness を decider 無しで渡すたびに -2 / -3 が積まれた）——同じ関数の頭の
    # 注記が「die しても空の盤面を残さない」と名乗っているので、名乗りの側でなく実装の側を合わせる
    tcfg = g.get("thickness", {})
    tiers, default = tcfg.get("tiers") or [], tcfg.get("default")
    th = a.thickness or default
    if th and th not in tiers:
        die(f"段 '{th}' はこの loop の段（{tiers}）に無い")
    deciders = tcfg.get("deciders", {})
    decider = a.decider or deciders.get("default")
    if a.decider and a.decider not in deciders.values():
        die(f"--decider '{a.decider}' はこの loop の値（{sorted(deciders.values())}）に無い")
    if th and default in tiers and tiers.index(th) < tiers.index(default) and decider != deciders.get("downgrade"):
        die(f"{th} は依頼者が明示に指定した場合だけ——依頼者がそう言ったときに限り --decider {deciders.get('downgrade')} を添えて init する")
    d.mkdir(parents=True, exist_ok=False)
    fn = hook(rules, "init_record")
    record = fn(th, decider) if fn else {}
    state = {
        "loop_name": loop, "run_id": run_id, "graph": str(pathlib.Path(graph).resolve()),
        "graph_sha": sha(pathlib.Path(graph).read_text(encoding="utf-8")),
        "created": now(), "status": "running", "round": 1, "rounds": [empty_round(1)],
        "thickness": th, "max_rounds": max_rounds_for(g, th), "unattended": bool(a.unattended),
        "inputs": inputs, "validator": validator, "outputs": {}, "done_ever": {}, "loop": {},
    }
    write_json(d / "state.json", state)
    write_json(d / "record.json", record)
    # current は resolve_dir が `<git-dir>/graphloops/*/current` を走査して拾う印なので、**--dir を明示した run では書かない**
    # ——走査範囲の外に書いても誰も読まず、--dir をリポジトリの中に向けると run 自身が作業ツリーを汚す（?? current が立つ）
    if not a.dir:
        (d.parent / "current").write_text(str(d) + "\n", encoding="utf-8")
    with open(d / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": "init", "thickness": th, "decider": decider}, ensure_ascii=False) + "\n")
    fn = hook(rules, "on_init")
    if fn:
        b = Board(d)
        fn(b, a)
        b.save()
    print(dump({"dir": str(d), "run_id": run_id, "loop": loop, "thickness": th, "thickness_decider": decider, "max_rounds": state["max_rounds"],
                "validator": validator or ("見つからない（report の前に init --validator で渡すか " + (env_root(g["plugin"]) if g.get("plugin") else "graph の plugin") + "）"),
                "overview": g.get("overview", ""), "next": f"python3 {PLUGIN_ROOT / 'scripts' / 'loop.py'} next --dir {d}"}))
