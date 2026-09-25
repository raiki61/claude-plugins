"""回す側が呼ぶコマンド。init / next / done / skip / answer / thicken / add / patch / finalize / status / record。"""
import datetime
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading

from . import pointers
from . import declared
from .advance import ENGINE_HELPERS, advance, emit_instance, engine_run_entry, helper_argv, launch_cwd, load_item, open_next_round
from .board import Board, empty_round
from .record import apply_writes
from .render import TOKEN, node_prompt, strip_prefix
from .rules import hook, load_rules, registry
from .schema import graph_text, load_graph, validate_schema
from .util import ANSWER_ACTIONS, IN_ROUND_ACTIONS, PLUGIN_ROOT, AnswerReject, BoardConflict, Reject, TERMINAL_STATUS, copy_worktree, die, dump, get_path, git, has_path, now, porcelain, protected_paths, read_json, repo_root, safe_name, set_path, sha, waiting, write_json
from .role_run import DELEGATE_TOOLS, SUPERSEDED, WRITE_TOOLS, Superseded, delegate_permission, delegate_settings, kill_all, pgid_path, probe_group, run_role, run_steps, stop_group, tooled_permission
from .validator import agent_def, find_validator, finalize, report_accepts, run_validator, env_root, traces


# **どの入力がパスかは graph が宣言し、engine は「どう確かめるか」だけを持つ。**
# 以前は名前の表（document・cwd）を engine が持っていた——engine は loop を知らない建前なのに、
# loop の入力名を 2 語だけ知っている形で、loop を足す人は engine を書き換える必要があった。
# 宣言（何がパスか）と手続き（実在の見方）を分けると、写しは 0 になる: graph の inputs が正本で、
# ここに在るのは kind の名前 → 見方の対応だけ（graphcheck が、知らない kind を静的に弾く）。
# rev は「この版を読め」と役に渡す git のリビジョンで、パスではない——実在の見方を持たない
# （engine は git を知らない。版が取れるかは rules が固定するときに確かめる）。choice は値の集合（宣言の values）から
# 選ぶ入力で、init が値を確かめる（値の意味は rules が持つ）
INPUT_KINDS = {"file": ("ファイル", pathlib.Path.is_file), "dir": ("ディレクトリ", pathlib.Path.is_dir),
               "rev": ("リビジョン", None), "choice": ("選択", None)}


def undeclared_inputs(g, inputs):
    """init の --input のうち、graph の inputs にも init の旗（CLI_FLAGS）にも無い鍵——どの節の穴も rules も読まないので効かない。
    拒まずに知らせる（受け付けていた呼びを壊さない）。黙って受けると、綴りを違えた選択が既定の流れに倒れても誰も気づかない"""
    known = set(g.get("inputs") or {}) | set(CLI_FLAGS) | {"cwd"}
    return sorted(k for k in inputs if k not in known)


def choice_input_errors(g, inputs):
    """kind が choice の入力に、宣言の values に無い値が渡されたか（誤りの文の一覧）"""
    errs = []
    for key, decl in (g.get("inputs") or {}).items():
        if isinstance(decl, dict) and decl.get("kind") == "choice" and inputs.get(key) is not None:
            if inputs[key] not in (decl.get("values") or []):
                errs.append(f"--input {key}={inputs[key]!r} は知らない値（使えるのは {decl.get('values')}。既定の流れなら {key} を渡さない）")
    return errs


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
    paths = path_inputs(g)
    missing = []
    for nid, n in g.get("nodes", {}).items():
        if not n.get("prompt_file"):
            continue
        try:
            tpl = node_prompt(graph_path, n, errors="replace")
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
    if not mod.check(graph, validator, emit=lines.append, node_keys="warn"):
        die(f"{graph}: graph の静的検査が通らない（init で止める。直してから回せ）\n"
            + "\n".join(l for l in lines if str(l).startswith("NG")))
    # 節の知らない鍵は止めずに知らせる（返りは init の notes に載せる）——外から持ち込んだ graph の節に利用者が書いた鍵で init を
    # 止めない（上位互換）。単体の graphcheck と台本では NG
    return [f"graph の静的検査の警告: {str(l)[5:]}" for l in lines if str(l).startswith("WARN ")]


# ---------------------------------------------------------------- next
def cmd_next(a):
    b = Board(resolve_dir(a))
    if b.state.get("halted"):
        # 止めた run（周の途中の問い・無人の問い・init --stop-after-round）——後の節は 1 つも出さない（報告も書かない。
        # 止めた所と理由は halted に在る）
        print(dump({"status": b.state["status"], "round": b.round, "ready": [], "halted": b.state["halted"],
                    "note": f"止めた run（halted: {b.state['halted'].get('by')}）。後の節は出さない"}))
        return
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
    if b.state.get("unfenced_delegates"):
        u = b.state["unfenced_delegates"]
        notes = [*notes, f"任せ先の柵（sandbox）を外した run（{u['at']}・理由: {u['reason']}）——任せ先は回す側が Agent で起こし、本物の作業ツリーと .git に書ける"]
    print(dump({
        # **run_id は直列化で綴りが変わらない印**（読了の柵が「この転写は回す側のものか」を見るのに使う。
        # パスは json.dumps が Windows の区切りを二重化するので印にできない）
        "status": b.state["status"], "round": b.round, "thickness": b.state["thickness"],
        "dir": str(b.dir), "run_id": b.state.get("run_id"), "notes": notes,
        **({"halted": b.state["halted"]} if b.state.get("halted") else {}),
        "ready": [{**{k: v for k, v in i.items() if k != "tree_before"}, **waiting(i)} for i in ready],
        "how": ("ready の全部を同時に始めてよい（同じ波）。"
                "**launch を持つ節（遮断系の cli・道具つきの agent・同じ役を続ける agent_continue・走らせるだけの engine_run）は loop.py launch を呼べ**"
                "——engine が役を claude -p で起こし（engine_run なら宣言のコマンドを走らせ）、子の終了を直接待ち、返答を out_path に書き、受け付け（done）まで済ませる。"
                "engine_run の結果は engine が終了コードから組む——done は拒まれる。"
                "拒まれたら同じ会話（--resume）に続きを頼む。時間の上限は無い。"
                "launch は役が終わるまで戻らず、前景だと Bash の上限（10 分）で切られるので Bash の背景実行に回す——**回したら手番を終えるな**。"
                "背景の出力のファイル（ハーネスが返す置き場。自分でリダイレクトしない）に launch の要約（\"launched\"）が出るまで、"
                "前景で 1 回 10 分未満の見に行くコマンドを繰り返せ（例: for i in $(seq 1 54); do grep -q '\"launched\"' <出力のファイル> && break; sleep 10; done）。"
                "完了の知らせを待たない（知らせで起こされずに止まった。実測 2026-09-25）。先頭が sleep のコマンドは Bash が拒み、上限の無い until ループは止まらないので使わない。"
                "返るのは 1 件 1 行の要約だけで、役の返答の本文は回す側に流れない。"
                "自分の Bash から claude を起こすな（出力をファイルに落とす綴りは auto mode の分類器が止める。実測 2026-09-15）。"
                "Agent ツールで起こすな（CLAUDE.md と git status が注入される——Agent の子の git status は止められない。engine は道具ゼロの子をリポジトリの外で起こす。返答の本文が回す側に入る）。"
                "launch は 1 件ずつ ok と why を返す——ok でない節は why を読み、拒否が続いた・子が落ちたなら "
                "loop.py relaunch --node <id> --reason <理由> で起こし直してから launch（relaunch は新しい試行を書いてから前の試行の子を木ごと止める）。stderr の with-auth: auth=… が "
                "none / keychain-miss なら認証が足りていない。engine が起こせない節（why が『前置ではない』『旗が無い』『権限の形』"
                "『定義が読めない』『claude が無い』）は迂回を組まず人に渡せ。"
                "launch を持たない agent の節（役の定義がこの環境に無い・道具の一覧を持たない・ファイルを書く道具を持つ役）は、手順書の agent の節の"
                "とおりに subagent_type に agent_type を渡して起こし、返答を out_path に書いて done --node <id> --agent-id <id>（agent_continue なら agent_id に SendMessage）。"
                "**任せ先（delegate）を持つ runner の節も launch を持つ**——engine が sandbox の中で起こす（作業ディレクトリは本物の写し、"
                "本物の作業ツリーと .git には書けない）。自分でやるな・Agent で起こすな。背景の任せ先（delegate.background）は受領を out_path に書いて "
                "done してから loop.py launch --node <id> を Bash の背景実行で立てよ（待たない）。任せ先の節が launch も unfenced も持たないなら、"
                "柵を組めない（graph に launch.delegate が無い）——迂回せず人に渡せ。unfenced を持つ（人が init --unfenced-delegates で柵を外した run）なら、"
                "delegate.model の汎用 agent を Agent ツールで立てて prompt_file を読ませよ。"
                "ほかの runner は自分でやる（skills があればその skill を呼ぶ。置き場のパスで渡された物は要る所だけ Read）。返答を out_path に保存して "
                "loop.py done --node <id>（別の場所に置いたなら --output <file>）。ready が空で status が running なら、done の直後にもう一度 next。"
                "柵を外した run で delegate の付いた節（background でない物）を Agent ツールで起こすときは**前景で**起こせ——その呼び出しの返りが"
                "任せ先の終了で、背景の完了の知らせ（入れ子や上限落ちで消える）に頼らない。任せ先が書かずに返った・落ちたら、"
                "loop.py relaunch --node <id> --reason <理由> で新しい置き場を作って起こし直す（前の試行が遅れて書いても別のファイルに落ち、記録に入らない）。"
                "delegate.background が真の節は待たない（受領を書いてすぐ done）"),
    }))


# ---------------------------------------------------------------- launch
# **engine が自分で起こしてよい形。** 起動が回す側の Bash・Agent ツールから engine の中へ移ると、1 件ずつ人（と
# auto mode の分類器）が見ていた審査がそのぶん外れる。代わりに engine が「自分が何を起こすか」をここで
# 言い切る——**graph の宣言を読んで判断する柵は柵ではない**（graph を書き換えられる立場の人が柵ごと
# 書き換えられる。README が受容として書いている「実行の正本をレビュー対象の木から取る」問題）。
# 起こしてよい形は役の定義（agent_def。起こす時に読み直す）で 2 つに分かれ、どちらも argv から機械で確かめる:
#   共通: 起こすのは engine 自身のインタプリタと、engine に同梱の層（scripts/with-auth.py）だけ。
#         層は claude 以外を名前で撥ねるので、engine が起こせる相手は claude に限られる
#   **旗は許可表で見る**（OWASP の Input Validation Cheat Sheet の allowlist——許す物だけを定め、ほかは全部拒む）。claude の後ろの
#         語を (旗, 値) に読み、形ごとの表に無い語（公式の別名 --allowed-tools・--flag=value の綴り・--add-dir・--mcp-config・
#         --plugin-dir・--agents・権限を外す旗・余分な位置引数）を拒む。各旗は 1 度きりで、--resume のほかは必須。値は engine が
#         決めた物と一致すること（_want_values）。以前の拒否リスト（名指しの旗の在否と 2 語の危ない旗）は、別名 1 語で抜けられた
#   道具ゼロの役: --tools "" と --setting-sources ""——道具が 1 つも無い子は何も実行できないので「権限の外で動く入れ子」にならない
#   道具つきの役: --setting-sources ""（利用者の設定・CLAUDE.md・プラグインのフックを読まない）・聞く先が無い
#         （--permission-prompts none）・渡す道具（--tools）が役の定義の道具と一致し、ファイルを書く道具を含まない・権限の形
#         （--permission-mode）と先に許す道具（--allowedTools）と設定（--settings。sandbox の形）が engine の決めた値
#         （role_run.tooled_permission）と一致する。graph は権限を配れない——graph の書き換えで起こせる物が広がらない
ISOLATED_FLAGS = ("-p", "--resume", "--model", "--effort", "--tools", "--setting-sources", "--append-system-prompt-file",
                  "--output-format")
TOOLED_FLAGS = ISOLATED_FLAGS + ("--allowedTools", "--permission-mode", "--permission-prompts", "--settings")
# 任せ先（delegate）の旗: 道具つきの役の旗から --effort を除いた物（任せ先はモデルだけを graph の delegate.model で名指す）
DELEGATE_FLAGS = tuple(f for f in TOOLED_FLAGS if f != "--effort")
BARE_FLAGS = ("-p",)          # 値を取らない旗
OPTIONAL_FLAGS = ("--resume",)  # 無くてよい旗（続ける会話の無い起動）
# 起こす役に依らない値
FIXED_VALUES = {"--setting-sources": "", "--permission-prompts": "none", "--output-format": "json"}


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


def _parse_flags(words, table):
    """claude の後ろの語を {旗: 値} に読む（-p の値は True）。返すのは (読んだ物, 拒む理由)。"""
    got = {}
    i = 0
    while i < len(words):
        w = words[i]
        if w not in table:
            return None, f"許可表に無い語 {w!r}——別名・=綴り・知らない旗・位置引数の子は engine の中から起こさない"
        if w in got:
            return None, f"旗 {w} が 2 度在る——後勝ちで値を差し替える子は engine の中から起こさない"
        if w in BARE_FLAGS:
            got[w] = True
            i += 1
            continue
        if i + 1 >= len(words):
            return None, f"旗 {w} に値が無い"
        got[w] = words[i + 1]
        i += 2
    missing = [f for f in table if f not in got and f not in OPTIONAL_FLAGS]
    if missing:
        return None, f"旗 {missing} が argv に無い——利用者の設定を読む子・聞く先を持つ子・形の決まらない子は engine の中から起こさない"
    return got, None


def _settings_refusal(value, want):
    """--settings の値が engine の値と同じ意味か（よければ None）。トップのキーは engine の値と同じ（sandbox だけか、空）で、
    permissions・hooks・env などを混ぜた子は起こさない。**denyWrite だけは包含で見る**——守る場所は起こす時に引き直した集合で、
    next と launch の間に作業ツリーが消えても通し、増えたら拒む（増えた回は relaunch で引き直す）。"""
    try:
        got = json.loads(value)
    except ValueError:
        return f"--settings が JSON として読めない（{value[:60]!r}）"
    want = json.loads(want)
    if not isinstance(got, dict) or set(got) != set(want):
        return f"--settings のキーが {sorted(got) if isinstance(got, dict) else value[:60]!r}——engine が決めた値は {sorted(want)}"
    if not want:
        return None
    gs, ws = got.get("sandbox"), want["sandbox"]
    fs = gs.get("filesystem") if isinstance(gs, dict) else None
    deny = fs.get("denyWrite") if isinstance(fs, dict) else None
    if not isinstance(deny, list) or not all(isinstance(x, str) for x in deny):
        return f"--settings の sandbox.filesystem.denyWrite が文字列の一覧でない（{str(gs)[:80]}）"
    rest = {**gs, "filesystem": {k: v for k, v in fs.items() if k != "denyWrite"}}
    wrest = {**ws, "filesystem": {k: v for k, v in ws["filesystem"].items() if k != "denyWrite"}}
    if rest != wrest:
        return f"--settings の sandbox が {json.dumps(rest, ensure_ascii=False)[:160]}——engine が決めた値は {json.dumps(wrest, ensure_ascii=False)[:160]}"
    lack = sorted(set(ws["filesystem"]["denyWrite"]) - set(deny))
    if lack:
        return f"--settings の denyWrite に守る場所 {lack} が無い（起こした後に作業ツリーが増えたなら relaunch で引き直せ）"
    return None


def _want_values(inst, d, perm, resume):
    """旗ごとの engine が決めた値。perm は role_run.tooled_permission（道具ゼロなら None）。resume は続きを頼む語か。"""
    want = {**FIXED_VALUES, "--model": d.get("model"), "--effort": d.get("effort")}
    if perm is None:
        want["--tools"] = ""
    else:
        want.update({"--tools": ",".join(d["tools"]), "--allowedTools": ",".join(perm["allowed_tools"]),
                     "--permission-mode": perm["permission_mode"]})
    # 続ける会話は engine が決めた物だけ——graph に任意の会話の番号を書いて、engine が起こしていない会話を開けない
    sid = inst.get("session_id")
    want["--resume"] = {"{session_id}", sid} - {None} if resume else {sid} - {None}
    return want


def _argv_refusal(argv, inst, d, perm, resume=False):
    """1 本の argv が起こしてよい形か（よければ None）。d は起こす時に読み直した役の定義、perm は engine が決めた権限の形。"""
    want_prefix = launch_prefix()
    if [_norm(a) for a in argv[:len(want_prefix)]] != [_norm(w) for w in want_prefix]:
        return (f"engine が起こしてよい前置ではない（graph の launch の via が {want_prefix} を指していない）"
                f"——先頭は {argv[:2]}")
    role_tools = d["tools"]
    if role_tools and ("*" in role_tools or any(x in WRITE_TOOLS for x in role_tools)):
        return f"全部の道具・ファイルを書く道具を持つ役（{role_tools}）——engine の中からは起こさない"
    got, why = _parse_flags(argv[len(want_prefix) + 1:], TOOLED_FLAGS if role_tools else ISOLATED_FLAGS)
    if why:
        return why
    want = _want_values(inst, d, perm, resume)
    for flag, val in got.items():
        if flag in BARE_FLAGS:
            continue
        if flag == "--settings":
            why = _settings_refusal(val, perm["settings"])
        elif flag == "--append-system-prompt-file":
            try:
                same = pathlib.Path(val).read_text(encoding="utf-8") == d["body"]
            except (OSError, UnicodeDecodeError):
                same = False
            why = None if same else f"--append-system-prompt-file {val!r} の中身が役の定義の本文でない"
        elif flag == "--resume":
            why = None if val in want["--resume"] else f"--resume が {val!r}——engine が続ける会話は {sorted(want['--resume'])}"
        elif flag in ("--tools", "--allowedTools"):
            same = sorted(val.split(",")) == sorted(want[flag].split(",")) if want[flag] else val == ""
            why = None if same else f"{flag} が {val!r}——役の定義から engine が決めた値は {want[flag]!r}（権限の形は graph でなく engine が決める）"
        else:
            why = None if val == want[flag] else f"{flag} が {val!r}——engine が決めた値は {want[flag]!r}"
        if why:
            return why
    return None


def launch_refusal(inst, cwd=None, board_dir=None):
    """起こせない理由（起こしてよければ None）。**理由は回す側に見せる**——黙って飛ばさない。

    形は instance の自己申告（launch.kind）でなく、**起こす時に読み直した役の定義**と、起こす時に engine が決め直した権限の形
    （role_run.tooled_permission。守る場所は子が起きる cwd と盤面の置き場から引く）で決める。"""
    launch = inst.get("launch") or {}
    argv = launch.get("argv") or []
    if launch.get("missing"):
        return f"この環境に {launch['missing']} が無い（PATH を確かめるか、人が起こす）"
    if launch.get("kind") == "delegate":
        return _delegate_refusal(inst, launch, board_dir)
    d = agent_def(inst.get("agent_type") or "")
    if d is None:
        return f"役 {inst.get('agent_type')!r} の定義が読めない——道具の形が決まらないので engine は起こさない"
    perm = tooled_permission(d["tools"], cwd, board_dir) if d["tools"] else None
    for words, resume in ((argv, False), (launch.get("resume_argv"), True)):
        if words:
            why = _argv_refusal(words, inst, d, perm, resume)
            if why:
                return why
    if not pathlib.Path(launch.get("stdin") or "").is_file():
        return f"材料 {launch.get('stdin')} が無い"
    return None


def _delegate_refusal(inst, launch, board):
    """任せ先（kind=delegate）を起こしてよい形か（よければ None）。**sandbox の設定は起こす瞬間に git から組み直して突き合わせる**
    ——next の後に作業ツリーが足された・盤面の argv が書き換えられた、どちらでも名指しが今の守る場所と揃わなければ起こさない。
    旗は役の節と同じ許可表で見る（_parse_flags——表に無い語・別名・2 度目の旗を拒む）。値は engine の値（role_run の
    delegate_permission・delegate_settings、モデルは graph の delegate.model）と一致を見る。graph の宣言は柵の根拠にしない"""
    protected = protected_paths([board] if board else [])
    if board is None or protected is None or launch.get("unprotected"):
        return "守る場所（作業ツリー・gitdir・共通の .git）を git から引けない——任せ先を sandbox で縛れないので起こさない"
    mode, allowed = delegate_permission()
    want = {**FIXED_VALUES, "--model": (inst.get("delegate") or {}).get("model") or "", "--tools": ",".join(DELEGATE_TOOLS),
            "--allowedTools": ",".join(allowed), "--permission-mode": mode}
    head = launch_prefix()
    for words, resume in ((launch.get("argv"), False), (launch.get("resume_argv"), True)):
        if not words:
            continue
        if [_norm(a) for a in words[:len(head)]] != [_norm(w) for w in head]:
            return f"engine が起こしてよい前置ではない（graph の launch の via が {head} を指していない）——先頭は {words[:2]}"
        got, why = _parse_flags(words[len(head) + 1:], DELEGATE_FLAGS)
        if why:
            return f"任せ先の argv: {why}"
        for flag, val in got.items():
            if flag in BARE_FLAGS or flag == "--append-system-prompt-file":
                continue   # 前置きの文（graph の preamble）は権限を運ばない
            if flag == "--settings":
                why = _settings_refusal(val, delegate_settings(protected))
            elif flag == "--resume":
                sid = inst.get("session_id")
                ok = {"{session_id}", sid} - {None} if resume else {sid} - {None}
                why = None if val in ok else f"--resume が {val!r}——engine が続ける会話は {sorted(ok)}"
            else:
                why = None if val == want[flag] else f"{flag} が {val!r}——engine が任せ先に決めた値は {want[flag]!r}"
            if why:
                return (f"任せ先の {why}（sandbox の名指し・道具・権限の形は起こす瞬間に git と role_run から組み直す。"
                        "next の後に作業ツリーが足されたなら relaunch で出し直せ）")
    if not pathlib.Path(launch.get("stdin") or "").is_file():
        return f"材料 {launch.get('stdin')} が無い"
    return None


BOARD_LOCK = threading.Lock()  # 同じ launch の中で並列に起こした役が、盤面を 1 本ずつ開いて書く錠


CONFLICT_RETRIES = 3


def _retry_on_conflict(d, step, allow_halted=False):
    """盤面を読み直して step(b) を当て直す枠——別のプロセスと版が衝突したら（Board.save の BoardConflict）、読み直して
    CONFLICT_RETRIES 回まで当て直す（Kubernetes client-go の retry.RetryOnConflict と同じ形）。保存は step の中でも後でもよい
    （_board_update は後で、launch の受け付けは accept_output の中で）。step は盤面の外に書かないか、書いても同じ中身の上書きに
    留める。trace の行は保存まで控えるので、当て直しても重ならない。BOARD_LOCK はスレッドの錠で、プロセスをまたいでは効かない。
    allow_halted は止めた run の盤面に書いてよい帳簿の書き込み（launch の締め）の印——Board.save が見る"""
    with BOARD_LOCK:
        for n in range(CONFLICT_RETRIES):
            b = Board(d)
            b.held_trace = []
            b.allow_halted = allow_halted
            try:
                return step(b)
            except BoardConflict:
                if n == CONFLICT_RETRIES - 1:
                    raise


def _board_update(d, fn, allow_halted=False):
    """錠の下で盤面を開き直し、fn(b) を当てて保存する（当て直しは _retry_on_conflict）。fn の返り値を返す。launch の印付けと締め、
    relaunch はどれも別のプロセスと同じ盤面を書きうる（止められた古い launch の締めと、relaunch・次の launch）"""
    def step(b):
        got = fn(b)
        b.save()
        return got
    return _retry_on_conflict(d, step, allow_halted)


def _accept_for_launch(d, iid, out_path):
    """run_role に渡す受け付け。**返答の不備（AnswerReject）だけを理由として返す**——役に返せば直る側。
    それ以外（節が待っていない・起こし直された・作業ツリーが変わった・盤面が進んだ）は例外のまま上げる（続きを頼んでも直らない）。
    保存の衝突は _retry_on_conflict が読み直して当て直し、回数まで負けたら conflict の印を立てて上げる（launch_one が done の案内を足す）。

    **本文は run_role の手元からでなく、開き直した instance の今の out_path から読む**（done と同じ読み元）。起こし直し
    （relaunch）は試行ごとに置き場を分けて古い試行を締め出す——手元の本文を渡すと、その締め出しを素通りして、
    遅れて終わった古い試行が新しい試行の instance を受け付けてしまう。"""
    def one(b):
        inst = pending_instance(b, iid)
        if inst.get("out_path") != out_path:
            raise Reject(f"'{iid}' は起こし直されている（今の置き場は {inst.get('out_path')}）——この試行の返答は受け付けない")
        try:
            text = pathlib.Path(out_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Reject(f"{out_path}: 読めない（{e}）") from e
        try:
            accept.msg = accept_output(b, iid, text, f"launch {out_path}")
        except AnswerReject as e:
            return str(e)
        return None

    def accept(_text):
        try:
            return _retry_on_conflict(d, one)
        except BoardConflict:
            accept.conflict = True   # 返答は置き場に在る
            raise
    accept.msg = None
    accept.conflict = False
    return accept


def _isolated_cwd(d, inst):
    """道具ゼロの役を起こす作業ディレクトリ——Git リポジトリの外の、run ごとに固定した一時ディレクトリ（公式文書 sub-agents の
    git status の項: 『Absent outside a Git repository』。2026-09-25 取得）。子に git status の写しを注入させない。同じ会話の
    続きの往復（--resume）は会話を起こした cwd の下から探すので、run の間は同じ置き場を使う。道具つきの役はリポジトリを
    読むので None（呼び出し側の cwd のまま）"""
    d_ = agent_def(inst.get("agent_type") or "")
    if d_ is None or d_["tools"] != []:
        return None
    p = pathlib.Path(tempfile.gettempdir()) / f"graphloops-isolated-{pathlib.Path(d).name}"
    p.mkdir(exist_ok=True)
    return str(p)


def _still_mine(d, inst):
    def still_mine():
        # 盤面を読むだけ（書かない）——途中で盤面に書く口を増やすと、別のプロセスとの競りで波ごと落ちる
        try:
            cur = read_json(pathlib.Path(d) / "state.json")["rounds"][-1]["instances"].get(inst["id"]) or {}
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return True   # 読めない回は止めない（止める向きの誤りは、健全な役を殺す）
        return cur.get("out_path") == inst["out_path"]
    return still_mine


def engine_run_refusal(inst, root):
    """走らせる節（kind=engine_run）の語が走らせてよい形か（よければ None）。**instance の申告でなく argv そのもので決める**
    ——同梱の語（ENGINE_HELPERS）は argv の頭が engine 自身のインタプリタと engine の置き場の scripts/<名前> に一致するときだけ
    宣言との突き合わせを免れ、それ以外の語は全部、走らせる直前に対象リポジトリのルート（root）の宣言を読み直し、中身が一致する
    ときだけ走らせる。root は盤面の instance から取らない（呼び元が util.repo_root で引く）。盤面（loop.py patch）や graph を
    書き換えても、宣言に無い語は engine の手で走らない"""
    launch = inst.get("launch") or {}
    steps = launch.get("steps")
    if not isinstance(steps, list) or not all(isinstance(s, dict) and isinstance(s.get("name"), str) and isinstance(s.get("argv"), list)
                                              and s["argv"] and all(isinstance(a, str) for a in s["argv"]) for s in steps):
        return "走らせる語（launch.steps）の形が [{name, argv}] でない"
    heads = [[_norm(a) for a in helper_argv(h)] for h in ENGINE_HELPERS]
    theirs = [s for s in steps if [_norm(a) for a in s["argv"][:2]] not in heads]
    if theirs:
        sha = declared.steps_sha(theirs)
        d = declared.read(root) if root else None
        if not d or d.get("sha") != sha:
            return (f"走らせる語（{[s['name'] for s in theirs]}）が対象リポジトリの宣言 {declared.DECL_NAME} と一致しない（sha {sha[:12]}）"
                    "——loop.py relaunch で今の宣言から計画し直せ")
    return None


def _engine_fallback(d, iid, reason):
    """engine の組んだ返答を使えないときに、同じ節を任せ先の節として出し直す（新しい試行。理由は instance と記録に残る）。
    拒まれた返答を同じ語で走らせ直しても同じ拒否になるので、出口を任せ先に作る"""
    def fall(b):
        prev = pending_instance(b, iid)
        new = emit_instance(b, prev["node"], None, attempt=prev.get("attempts", 1) + 1, engine_fallback=reason)
        new["attempt_log"] = (prev.get("attempt_log") or []) + [{"at": new["emitted_at"], "reason": reason,
                                                                  "prev_emitted_at": prev["emitted_at"], "prev_out_path": prev["out_path"]}]
        b.trace("engine_fallback", instance=iid, reason=reason)
        return new["id"]
    return _board_update(d, fall)


def launch_engine_run(d, inst):
    """走らせる節（kind=engine_run）を 1 つ走らせ、終了コードから engine が返答を組み、受け付け（accept_output）まで済ませる。
    返答を組むのは rules の ENGINE_RUNS[builtin].reply で、任せ先が要る結果（役の判断が要る・受け付けが拒んだ）なら
    同じ節を任せ先の節として出し直す（_engine_fallback）。回す側は結果を書かない（done は engine_run を拒む）"""
    got = {"id": inst["id"], "node": inst["node"], "out_path": inst["out_path"]}
    root = repo_root()
    why = engine_run_refusal(inst, root) if root else "対象リポジトリのルートが引けない（git rev-parse --show-toplevel）"
    if why:
        return {**got, "ok": False, "why": why}
    launch = inst["launch"]
    log_dir = pathlib.Path(d) / "runs" / pathlib.Path(inst["out_path"]).parent.name / safe_name(inst["id"] + f".a{inst.get('attempts', 1)}")
    try:
        runs = run_steps(launch["steps"], root, log_dir, pgid_file=pgid_path(inst["out_path"]),
                         still_mine=_still_mine(d, inst))
    except Superseded:
        return {**got, "ok": False, "why": SUPERSEDED, "superseded": True}
    with open(pathlib.Path(d) / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": "engine_run", "instance": inst["id"], "node": inst["node"],
                            "runs": [{k: r.get(k) for k in ("name", "exit", "wall_s", "error")} for r in runs]}, ensure_ascii=False) + "\n")
    fallback = None
    runs_short = [{k: r.get(k) for k in ("name", "exit", "wall_s")} for r in runs]
    with BOARD_LOCK:
        try:
            b = Board(d)
            cur = pending_instance(b, inst["id"])
            if cur.get("out_path") != inst["out_path"]:
                return {**got, "ok": False, "why": SUPERSEDED, "superseded": True}
            reply = engine_run_entry(b, b.nodes[inst["node"]])["reply"](b, inst["node"], launch, runs)
            if "fallback" in reply:
                fallback = reply["fallback"]
            else:
                text = json.dumps(reply["reply"], ensure_ascii=False)
                pathlib.Path(inst["out_path"]).write_text(text, encoding="utf-8")
                try:
                    msg = accept_output(b, inst["id"], text, f"launch {inst['out_path']}")
                except AnswerReject as e:
                    fallback = f"engine が組んだ返答を受け付けが拒んだ（{str(e)[:400]}）"
        except (Reject, SystemExit) as e:   # 節が待っていない・盤面の競り——返答を組み直しても直らない。同じ波の兄弟を道連れにしない
            return {**got, "ok": False, "why": f"受け付けまで進めない（{type(e).__name__}: {e}）", "runs": runs_short}
    if fallback:
        new = _engine_fallback(d, inst["id"], fallback)
        return {**got, "ok": False, "fell_back": True, "why": f"任せ先の節に回した（{new}。next の ready に任せ先の節として出る）: {fallback}",
                "runs": runs_short}
    return {**got, "ok": True, "why": None, "done": msg, "runs": runs_short}


def launch_one(d, inst, max_resumes, cwd=None):
    """1 節を起こして受け付けまで済ませる（run_role）。返すのは回す側と記録に見せる 1 件ぶんの要約だけ——役の返答の
    本文は回す側の会話に流さない。cwd は子の作業ディレクトリ（レビュー対象の作業ツリー）——dontAsk の子は作業ディレクトリの
    外の git を拒まれる（role_run.tooled_permission の実測）ので、launch を呼んだ場所でなく盤面の inputs.cwd で起こす。
    走らせる節（engine_run）は対象リポジトリのルート（repo_root）で走るので、この cwd は使わない。"""
    if (inst.get("launch") or {}).get("kind") == "engine_run":
        return launch_engine_run(d, inst)
    got = {"id": inst["id"], "node": inst["node"], "out_path": inst["out_path"]}
    why = launch_refusal(inst, cwd, d)
    if why:
        return {**got, "ok": False, "why": why}
    launch = inst["launch"]
    background = bool(launch.get("background"))
    accept = None if background else _accept_for_launch(d, inst["id"], inst["out_path"])
    still_mine = _still_mine(d, inst)
    # 背景の線は誰も待たない（周の締めも次の周も線を待たない）。時間の上限はどの節にも付けない
    out_path = launch["result_path"] + ".tmp" if background else inst["out_path"]
    run_cwd, env, work = _isolated_cwd(d, inst) or cwd, None, None
    if launch.get("kind") == "delegate":
        # 任せ先の作業ディレクトリは本物の外に作る写し。TMPDIR も同じ置き場の下に向けるので、任せ先が mktemp -d で作る写しも
        # ここに溜まり、終わったら消える。返答が名指しして後で読まれるファイル（背景の線の patch 等）は GRAPHLOOPS_KEEP の下に
        # 置かせ、そこだけ残す（中身が無ければ置き場ごと消す）——写しと TMPDIR は大きく、線は周ごとに立つので溜めない
        import tempfile
        work = pathlib.Path(tempfile.mkdtemp(prefix="graphloops-delegate-"))
        (work / "tmp").mkdir()
        (work / "keep").mkdir()
        try:
            run_cwd = copy_worktree(work / "work")
        except Reject as e:
            import shutil
            shutil.rmtree(work, ignore_errors=True)
            return {**got, "ok": False, "why": str(e)}
        env = {**os.environ, "TMPDIR": str(work / "tmp"), "GRAPHLOOPS_KEEP": str(work / "keep")}
    try:
        r = run_role(launch["argv"], launch["stdin"], out_path,
                     accept=accept, resume_argv=launch.get("resume_argv"), max_resumes=0 if background else max_resumes,
                     log_path=pathlib.Path(d) / "trace.jsonl", still_mine=still_mine, cwd=run_cwd, env=env,
                     meta={"instance": inst["id"], "node": inst["node"], "agent_type": inst.get("agent_type"),
                           "attempt": inst.get("attempts", 1), "form": launch.get("form")})
    finally:
        if work:
            import shutil
            for part in ("work", "tmp"):
                shutil.rmtree(work / part, ignore_errors=True)
            if not any((work / "keep").iterdir()):
                shutil.rmtree(work, ignore_errors=True)
    if background and r["ok"]:
        # 線の結果は書き終えた物だけが置き場に在る（読む側は .tmp を読まない）。返答は役の返答と同じ読み方（parse_output——
        # 囲いの ```json も解く）で JSON に直してから置く。読めなければ本文のまま置き、読む側（rules）が使えない結果として扱う
        try:
            body = parse_output(pathlib.Path(out_path).read_text(encoding="utf-8"))
            pathlib.Path(out_path).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        except (AnswerReject, OSError, UnicodeDecodeError):
            pass
        os.replace(out_path, launch["result_path"])
    last = r["runs"][-1] if r["runs"] else {}
    if accept is not None and accept.conflict:
        # 盤面の保存が別のプロセスと当て直しの回数まで競って負けた（BoardConflict）。返答は置き場に在るので、done で受け付けられる
        r["why"] += f"——返答は {inst['out_path']} に在る。loop.py done --node {inst['id']} で受け付けよ"
    if work and work.exists():
        got["kept"] = str(work / "keep")   # 任せ先が残した物（返答が名指しするファイル）の置き場
    return {**got, "ok": r["ok"], "why": r["why"], "session_id": r["session_id"], "superseded": r["superseded"],
            "resumes": len(r["runs"]) - 1, "rejections": r["rejections"], "done": accept.msg if accept else None,
            # total_cost_usd は会話の累計（続きを頼むたびに増える。実測 2026-09-25・haiku: 0.0137 → 0.0166 → 0.0198）——足さずに最大を取る
            "cost_usd": max((x.get("total_cost_usd") or 0 for x in r["runs"]), default=0) or None,
            "permission_denials": sum(len(x.get("permission_denials") or []) for x in r["runs"]),
            "stderr": "" if r["ok"] else (last.get("stderr") or "")}


def cmd_launch(a):
    """engine が役を起こし、返答を置き場に書き、受け付け（done）まで済ませる。回す側は役の返答の本文に触れない。

    **なぜ engine が起こすか。** 回す側が Bash から起こす形は、出力を out_path に落とす綴りだと auto mode の
    分類器が『Auto-Mode Bypass』で止める（実測 2026-09-15）。道具ゼロの役を Agent ツールへ逃がすと CLAUDE.md が
    注入されて遮断が名ばかりになる（実測 2026-09-12）。道具つきの役を Agent ツールと中継の AI で起こすと、
    書いていないのに『書いた』と返す・続きの返答が回す側へ戻る・完了の知らせが迷って止まる、が起きた（実測 2026-09-24〜25）。
    **終わりは子プロセスの終了で直接待つ**（role_run.run_role）。時間の上限は付けない。何を起こすかは launch_refusal が機械で縛る。
    """
    d = resolve_dir(a)
    want = getattr(a, "node", None)
    picked = []

    def mark(b):
        picked.clear()   # 版の衝突で当て直すたびに組み直す（盤面の外の一覧に行を重ねない）
        # 背景の任せ先は受領を done した後に起こす（名指しのときだけ。1 試行 1 回の柵は下の launched_at が同じく当たる）
        ready = [i for i in b.rd["instances"].values()
                 if i.get("launch") and (not want or i["id"] == want)
                 and (i["status"] == "pending" and not i["launch"].get("background")
                      or want and i["status"] == "done" and i["launch"].get("background"))]
        if not ready:
            raise Reject("engine が起こせる節が無い（next の ready に launch を持つ節が在るか、--node の綴りを確かめよ。"
                         "背景の任せ先は受領を done してから --node で名指しして起こす。"
                         "launch を持たない役の節は回す側が Agent で起こす）")
        at = now()
        for i in ready:
            if i.get("launched_at"):
                # 起こすのは 1 つの試行につき 1 回だけ。起動中の節は波の遅い節を待つ間も pending のまま ready に出るので、
                # ここで拾うと 2 つの子が同じ置き場に書いて競る。止まった起動・拒まれた起動からの出口は relaunch
                # （launched_at の無い新しい試行を作る）
                picked.append({"id": i["id"], "node": i["node"], "ok": False,
                               "why": f"この試行は {i['launched_at']} に起こし済み（{i.get('launch_state')}）——生きている launch を待つか、"
                                      f"loop.py relaunch --node {i['id']} --reason <理由> で起こし直してから launch"})
                continue
            i.update(launch_state="running", launched_at=at)
            b.trace("launch", instance=i["id"])
        return [dict(i) for i in ready if i.get("launched_at") == at and i.get("launch_state") == "running"]

    todo = _board_update(d, mark)
    b0 = Board(d)
    max_resumes = int(b0.graph.get("launch", {}).get("resume_on_reject") or 0)
    cwd = launch_cwd(b0)  # 無い場所なら起こす時に OSError で落ち、why に出る
    # **launch 自身が止められても子を残さない**: 止める信号の口は loop.py の main が全コマンドに立てる
    # （role_run.install_stop_handlers）。ここは例外で抜けた回の後始末
    try:
        if len(todo) == 1:
            results = [launch_one(d, todo[0], max_resumes, cwd)]
        elif todo:
            # 同じ波に載った役は互いに依存しない。直列に待つと素直に足し算になる
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(todo))) as ex:
                results = list(ex.map(lambda i: launch_one(d, i, max_resumes, cwd), todo))
        else:
            results = []
    finally:
        kill_all()

    def settle(b):
        for r in results:
            i = b.rd["instances"].get(r["id"])
            if r.get("fell_back"):
                continue   # 任せ先の節として出し直した（新しい試行は _engine_fallback が書いた）——why はそのまま返す
            if i is None or i.get("out_path") != r["out_path"]:
                # 起こし直された（試行が進んだ）——古い試行の結果を新しい試行に書かない。回す側に返す行も言い換える:
                # relaunch に止められた子は『子が落ちた』に見え、それに従って relaunch すると生きている新しい試行を止める
                r.update(why=SUPERSEDED, superseded=True)
                continue
            i["launch_state"] = "ended"
            if r.get("session_id"):
                i["session_id"] = r["session_id"]
            log = i.setdefault("attempt_log", [])
            # 起こし直しの回数と理由: 拒まれて同じ会話に続きを頼んだ（resume）・拒まれたまま上限に達した（rejected）
            for j, why in enumerate(r.get("rejections") or []):
                log.append({"at": now(), "kind": "resume" if j < r["resumes"] else "rejected", "reason": why})
            if not r["ok"] and r.get("why") and not r.get("rejections"):
                log.append({"at": now(), "kind": "failed", "reason": r["why"]})
            b.trace("launched", id=r["id"], ok=r["ok"], why=r.get("why"), session_id=r.get("session_id"),
                    resumes=r.get("resumes"), stderr=(r.get("stderr") or "")[-200:])

    if results:
        try:
            _board_update(d, settle, allow_halted=True)   # 帳簿の締め（記録は進めない）——止めた run でも一覧を返す
        except BoardConflict:
            # 盤面を別のプロセスと競って書けなかった。結果の一覧は回す側に必ず返す（trace にも行は在る）
            for r in results:
                r["settle"] = "盤面に起こし直しの記録を書けなかった（別のプロセスと競った）"
    print(dump({"launched": picked + results,
                "how": ("ok の節は受け付けまで済んでいる（done は要らない）——次は loop.py next。"
                        "ok でない節は why を読め: 受け付けの拒否が続いた・子が落ちた、なら "
                        "loop.py relaunch --node <id> --reason <理由> で起こし直してから launch（前の試行の子は relaunch が止める）。"
                        "why が『起こし直された古い試行』の行は次の手が要らない（新しい試行の launch を待て）。"
                        "stderr の with-auth: auth=… が none / keychain-miss なら認証が足りていない（inherited / keychain なら役の側）。"
                        "返答は out_path に在る（読むのは要る所だけ）。engine が起こせない節（why が『前置ではない』『旗が無い』"
                        "『権限の形』『定義が読めない』）は迂回を組まず人に渡せ。"
                        "走らせる節（engine_run）の why が『任せ先の節に回した』なら次の手は next（任せ先の節として出る）。"
                        "『宣言と一致しない』なら loop.py relaunch で今の宣言から計画し直してから launch")}))


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
        raise AnswerReject("返答が中身を持たない（空か空白だけ）——役が何も返していないか、"
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
    raise AnswerReject("\n".join(lines))


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
    inst = pending_instance(b, a.node)
    if inst.get("mode") == "engine_run":
        raise Reject(f"'{a.node}' は engine が走らせる節（mode=engine_run）——結果は engine が終了コードから組む。loop.py launch を呼べ"
                     "（回す側や任せ先が書いた結果は受け付けない。任せ先に回すのは engine が決める）")
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
        raise Reject(f"返答が無い——--output か標準入力で渡すか、{inst.get('out_path')} に置け（engine が起こす節は loop.py launch が書く）")
    if inst.get("mode") == "cli" and a.agent_id:
        raise Reject("cli の遮断系は engine が起こすので agent_id は無い（会話の番号は launch が盤面に残す）——--agent-id を渡すな")
    print(accept_output(b, a.node, text, read_from, agent_id=a.agent_id, accept_tree_change=a.accept_tree_change))


def _refuse_halted(b):
    """周の途中の問いで止めた run（halted）の受け付けを、中身の仕事（out/ への書き込み・post_check）の前に拒む。
    止めた run への書き込み全部の拒否は Board.save が持つ（ここは早く拒むための入口の 1 か所だけ）"""
    if b.state.get("halted"):
        raise Reject(f"この run は周の途中の問いで止めた（halted: {b.state['halted'].get('node')}）——役を起こさない・受け付けない")


def pending_instance(b, node):
    """受け付けを待っている instance（待っていなければ Reject——役に返しても直らない側）。周の途中の問いで止めた run（halted）の
    instance も待っていない——done と launch の受け付けがここを通るので、止めた run の記録は進まない"""
    _refuse_halted(b)
    inst = b.rd["instances"].get(node)
    if not inst:
        raise Reject(f"この周に節 '{node}' は出ていない（loop.py next で確かめよ）")
    if inst["status"] != "pending":
        raise Reject(f"節 '{node}' は既に {inst['status']}")
    return inst


def accept_output(b, node, text, read_from, agent_id=None, accept_tree_change=None):
    """返答の本文を受け付けて盤面と記録に写す（done の中身。loop.py launch も同じここを呼ぶ）。返すのは回す側に見せる 1 行。

    **返答の中身・形の不備は AnswerReject**（役に返せば直る——launch は同じ会話に続きを頼む）、それ以外の不備は Reject。
    盤面を書くのは最後の b.save() だけ——拒んだ呼び出しは盤面（state.json / record.json）を変えない。"""
    inst = pending_instance(b, node)
    nid = inst["node"]
    n = b.nodes[nid]
    # **出した後に graph が変わり、deps が増えた節は、増えた deps を待つ。** 出した時点で揃っていた deps だけを信じると、
    # run の途中で足した前段（例: 修正の前の事前審査）を飛ばした返答を受け付ける（実測 2026-09-24: 回す側が手で待たせた）
    if not b.deps_met(nid):
        wait = [d for d in n.get("deps", []) if b.node_state(d) == "pending"]
        raise Reject(f"節 '{node}' の deps {wait} がまだ済んでいない（出した後に graph が変わった）——先にそちらを回せ（loop.py next）")

    inst["read_from"] = read_from
    if n.get("schema"):
        output = parse_output(text)
        errs = validate_schema(output, n["schema"])
        if errs:
            raise AnswerReject("返答が型に合わない（直して done し直す。回す側が中身を補ってはいけない——役に返させろ）:\n"
                               + "\n".join(f"  - {e}" for e in errs))
    else:
        # 本文を返す節にも空の検査を当てる（schema 節は minLength が同じ形を落としている）。空を受けると
        # 0 バイトの report.md が残り、『人が決めること』が黙って消える（実測: --output <空> も </dev/null> も exit 0 だった）。
        if not text.strip():
            raise AnswerReject(f"節 '{nid}' の返答が空——本文を返す節に空は受け付けない（役が何も返していないか、{inst.get('out_path')} に書けていない）")
        output = {"text": text}
    # 番号で指した欄を名前に戻す（engine/pointers.py）。以降の検査・記録・報告は名前だけを見る
    errs = pointers.resolve(output, n.get("pointers"), inst.get("pointers"))
    if errs:
        # 範囲外の番号も、一覧を固めていない instance への番号も、役が書き直せば直る（番号を直すか名前で書く）
        raise AnswerReject(f"{nid}: " + "; ".join(errs))
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
                           if i != node and "tree_before" in x and x["status"] == "pending")
            who = f"（同じ波で保護対象の instance が他に {len(peers)} 件走っている: {peers}——変えたのがこの instance とは限らない）" if peers else ""
            if not accept_tree_change:
                raise Reject(f"{inst['run_by']} の前後で作業ツリーが変わっている: {diff}{who}。戻してから done し直すか、自分の変更なら --accept-tree-change <理由>")
            b.state.setdefault("git_mismatches", []).append({"instance": node, "diff": diff, "accepted": accept_tree_change,
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
            raise AnswerReject(f"項目に無い {key} を返している: {sorted(extra)}")
        remaining = sorted(want - got)
    # 段の昇格（降格は engine が拒む）
    tf = n.get("thickness_from")
    if tf and has_path(output, tf):
        want = get_path(output, tf)
        if want not in b.tiers:
            raise AnswerReject(f"段 '{want}' はこの loop の段（{b.tiers}）に無い")
        if b.tiers.index(want) < b.tiers.index(b.state["thickness"]):
            raise AnswerReject(f"段を {b.state['thickness']} から {want} に下げようとしている。降格は依頼者の指定で init に渡す（回す側の自己判断による降格＝さぼり降格を禁ずる）")
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
        try:
            note = fn(b, nid, output, item)
        except AnswerReject:
            raise
        except Reject as e:  # 節ごとの整合（rules）は返答の中身を見る——役に返せば直る側に揃える
            raise AnswerReject(str(e)) from e
        if note:
            notes.append(note)
    apply_writes(b, nid, output, item)
    check = hook(b.rules, "check_record")
    if check:
        errs = check(b, nid)  # 今 done している節はまだ done の印が無いので名指しで渡す（走った事実との突合に要る）
        if errs:
            raise AnswerReject("記録の整合が取れない（役に返させ直す。回す側が補ってはいけない）:\n"
                               + "\n".join(f"  - {e}" for e in errs))
    f = b.dir / "out" / f"r{b.round}" / (safe_name(node) + ".json")
    write_json(f, output)
    if n.get("save_text_as"):
        (b.dir / n["save_text_as"]).write_text(output["text"], encoding="utf-8")
        notes.append(f"本文は {b.dir / n['save_text_as']} に保存した")
    b.state["outputs"][nid] = {"file": str(f.relative_to(b.dir)), "round": b.round, "instance": node}
    # **綴りは 1 つに決める。** 以前はこの 2 行が同じ f を 2 つの綴りで書いていた——outputs は盤面からの相対、
    # instance は `--dir` をそのまま前に付けた綴り。後者は**記録されていない過去の作業ディレクトリ**に錨を持つので、
    # 相対の `--dir` で回した run を別の作業ディレクトリから開くと読めない（実測 2026-09-13: 絶対 --dir で開いても
    # cwd=/tmp から ref('raw') が SystemExit 2。最終報告の節でだけ露出した）。盤面からの相対に揃えると、
    # 錨は「いまの呼び出しが渡した --dir」1 つになり、読む側に規約の知識が要らなくなる。
    inst.update({"status": "done", "done_at": now(), "output_file": str(f.relative_to(b.dir))})
    if agent_id:
        inst["agent_id"] = agent_id
    b.trace("done", instance=node, sha=sha(text))
    msg = f"ok {node} を受け付けた（読んだ先: {read_from}）"
    if remaining:
        item = dict(item)
        base = cover["items_at"].split(".", 1)[1]
        item[base] = [x for x in item[base] if x[cover.get("key", "id")] in remaining]
        k = sum(1 for i in b.rd["instances"] if i.startswith(f"{nid}[{item['key']}]"))
        new = emit_instance(b, nid, item, suffix=f"#{k + 1}")
        msg += f"。ただし答えが欠けた項目がある: {remaining}——欠けた分だけ {new['id']} として出し直した（無言の省略を『なし』と読まない）"
    if "fan_out" not in n:
        b.rd["done"][nid] = {"at": now(), "instance": node}
        b.state["done_ever"][nid] = b.round
    b.save()
    # done の 1 行にも run_id を載せる——done だけを打った session でも印が転写に載る（読了の柵が読む）
    return "。".join([msg, *notes]) + f"。続きは loop.py next（run {b.state.get('run_id')}）"



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
    in_round = bool(ph.get("in_round"))
    if in_round and ans not in IN_ROUND_ACTIONS:
        raise Reject(f"周の途中の問い（in_round）に '{ans}' は使えない（使えるのは {list(IN_ROUND_ACTIONS)}）")
    ph["note"] = a.note or ""
    fn = hook(b.rules, "on_answer_in_round" if in_round else "on_answer")
    if fn:
        fn(b, ph, ans)
    b.state.pop("pending_human")
    b.trace("answer", answer=ans, kinds=ph.get("kinds"))
    if in_round:
        # 問うた節をここで済ませる（ask では done の印を付けない）。continue は同じ周のまま先へ、stop は run をその場で止める
        b.rd["done"][ph["node"]] = {"at": now(), "builtin": f"answer:{ans}"}
        b.state["done_ever"][ph["node"]] = b.round
        if ans == "stop":
            b.state["status"] = "stopped"
            b.state["halted"] = {"node": ph["node"], "round": b.round, "by": "answer", "reason": ph["note"]}
    elif ans == "stop":
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
        if not open_next_round(b, ph["node"]):
            b.rd["done"][ph["node"]] = {"at": now(), "builtin": f"answer:{ans}"}
            b.state["done_ever"][ph["node"]] = b.round
            b.save()
            print(f"ok 答え '{ans}' を記録した。init --stop-after-round {b.state['stop_after_round']} の指定で、次の周は開かずに止めた（halted）")
            return
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
    """rules の add に渡し、返りが名指す instance（積んだ欄を読む、まだ起こしていない instance）を描き直す。
    返りは文か {msg, redraw: [instance の id]}——プロンプトは instance を出した時点で固まるので、描き直さないと
    積んだ物が起こす前の役に届かない（黙って落ちる）"""
    b = Board(resolve_dir(a))
    fn = hook(b.rules, "add")
    if not fn:
        raise Reject("このループの rules は add を受け付けない")
    got = fn(b, read_json(a.file), a.reason)
    msg, redraw = (got, []) if isinstance(got, str) else (got["msg"], got.get("redraw") or [])
    bad = [x for x in redraw if (b.rd["instances"].get(x) or {}).get("status") != "pending"]
    if bad:
        die(f"rules の add が描き直せと言う {bad} は、今の周の待っている instance でない（rules の欠陥）")
    lines = []
    for iid in redraw:
        prev = b.rd["instances"][iid]
        new = reissue(b, prev, f"add で積んだ物を届けるため描き直した（{a.reason}）")
        retire_out(prev["out_path"], prev.get("attempts", 1))
        b.trace("redrawn", instance=iid, attempt=new["attempts"], reason=a.reason)
        lines.append(f"{iid} を試行 {new['attempts']} として描き直した（prompt_file {new['prompt_file']}・out_path {new['out_path']}）"
                     + ("" if new.get("launch") else "——engine が起こさない節なので、前の試行を起こしていたら止めて、新しい prompt_file で起こせ"))
    b.trace("add", reason=a.reason)
    b.save()
    print("ok " + msg + "".join("。" + x for x in lines))


def cmd_patch(a):
    """記録（既定）か盤面（state. 接頭）の手当て。痕跡は state.patches と trace に残る。

    盤面も許すのは、run の途中で graph と雛形が変わると rules の私有の鍵が足りずに next が止まり、
    記録側の手当てでは届かないから（実測 2026-09-12: 雛形が新しい loop_state の鍵を読み、回す側が
    state.json を手で書き換えて続けた——手当ての口が盤面の壊れ方を覆っていなかった）。
    """
    b = Board(resolve_dir(a))
    b.allow_halted = True   # 手当ては止めた run にも当てられる（痕跡は patches に残る）
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
    b.allow_halted = True   # 記録の仕上げと検証器は、止めた run でも回せる（報告は書かない）
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
        "max_rounds": st["max_rounds"], "stop_after_round": st.get("stop_after_round"), "unattended": st["unattended"],
        "halted": st.get("halted"),
        "this_round": {"done": sorted(b.rd["done"]), "na": b.rd["na"], "skipped": b.rd["skipped"], "empty": b.rd["empty"],
                       "pending_instances": [{"id": i["id"], **waiting(i)} for i in b.rd["instances"].values() if i["status"] == "pending"]},
        "pending_human": st.get("pending_human"), "validator": st.get("validator"),
    }))


def cmd_relaunch(a):
    """待っている instance を起こし直す——新しい試行を盤面に書いてから、**前の試行の子を木ごと止める**。同じ節・同じ項目で
    出し直し、試行の回数と理由を盤面と trace に刻む。

    **前の試行を止める**: engine が起こした試行（launch）は、子のグループの番号を置き場の隣（role_run.pgid_path。role_run が
    書き、子が終わると消す）に持つ。書く前に、その印を**信号を送らずに**確かめ（probe_group: 読めない・開始時刻を確かめ
    られない、なら新しい試行を作らずに拒む）、新しい試行を保存した後に 1 回だけ止める。止めるのが先だと、止められた古い
    launch が締め（settle）で先に盤面を進め、ここの保存が版の衝突で落ちた（実測 2026-09-25: 生きている launch への relaunch が
    4 回とも exit 2）。保存が先なら、古い launch の締めは置き場の不一致で『起こし直された古い試行』に言い換わる。止めた直後に
    古い launch が続きの往復の子を起こしても、その子は起こした直後に盤面を読んで自分で止まる（still_mine。role_run._spawn の注記）。
    engine が起こしていない試行（Agent で起こした役・任せ先）は engine がプロセスを持たないので、回す側が前の試行を止めてから relaunch する。
    **前の試行を締め出す**: 新しい試行は別の out_path（.a<試行>）を持ち、前の置き場に在った物は .stale-a<試行> へ退ける。
    前の試行が遅れて書いても、done は今の試行の置き場しか読まない（Temporal の task token が試行ごとに一意なのと同じ）。
    作業ツリーの基準点（tree_before）は前の試行の物を引き継ぐ——取り直すと、前の試行が書き換えた作業ツリーが基準に入り、突合を素通りする"""
    d = resolve_dir(a)

    def handed_prev(b):
        prev = b.rd["instances"].get(a.node)
        # 起こし直せるのは他へ渡した instance だけ: engine が起こす節（launch）・Agent で起こす役の節・任せ先の付いた節。
        # 回す側が自分でやる節は起こし直さない（圧縮後に読み直した回す側が、自分の作業を締め出す道になる）
        handed = prev is not None and (prev.get("launch") or not b.is_runner(b.nodes[prev["node"]]) or b.nodes[prev["node"]].get("delegate"))
        if prev is None or prev["status"] != "pending" or not handed:
            raise Reject(f"'{a.node}' は今の周の、他へ渡して待っている instance でない（起こし直せるのは pending で、役の節か任せ先の付いた節だけ。"
                         "回す側が自分でやる節は起こし直さない）")
        return prev

    prev0 = handed_prev(Board(d))
    old = pathlib.Path(prev0["out_path"])
    # 止めるのは今の試行と、それより前の試行の印（前の relaunch が止め切れずに残した子を、次の relaunch が止め直す口）
    marks = [pgid_path(old)] + [pgid_path(x["prev_out_path"]) for x in prev0.get("attempt_log") or [] if x.get("prev_out_path")]
    for m in marks:
        _pgid, why = probe_group(m)
        if why:
            raise Reject(f"前の試行の子を確かめられない（{why}）——新しい試行は作っていない")

    def bump(b):
        prev = handed_prev(b)
        if prev["out_path"] != str(old):
            raise Reject(f"'{a.node}' は読んでいる間に別の relaunch で起こし直された（今の置き場は {prev['out_path']}）——新しい試行は作っていない")
        new = reissue(b, prev, a.reason)
        b.trace("relaunched", instance=a.node, attempt=new["attempts"], reason=a.reason)
        return dict(new), prev.get("attempts", 1)

    new, n = _board_update(d, bump)
    retire_out(old, n)
    whys = [w for w in (stop_group(m) for m in marks) if w]
    if whys:
        die(f"新しい試行（{new['out_path']}）は作ったが、前の試行の子を止められない（{'; '.join(whys)}）——止まるまで launch するな"
            f"（もう一度 relaunch --node {new['id']} すれば、前の試行の印も止め直す）")
    print(dump({"relaunched": {k: v for k, v in new.items() if k != "tree_before"},
                "how": ("新しい out_path に書かせて起こし直せ（prompt_file は描き直した。前の試行の置き場は読まれない）。"
                        "engine が起こした前の試行の子は止めた。Agent で起こした前の試行は engine が止められないので、回す側が止めてから起こせ")}))


def reissue(b, prev, reason):
    """待っている instance を、同じ節・同じ項目の新しい試行として出し直す（プロンプトを今の盤面で描き直す）——新しい instance を返す。
    relaunch（起こし直し）と add（起こす前の判定役に積んだ依頼を届ける）が呼ぶ。新しい試行は別の out_path（.a<試行>）を持つ。
    作業ツリーの基準点（tree_before）は前の試行の物を引き継ぐ。**盤面の外には書かない**（relaunch が _board_update の当て直しの
    中から呼ぶ）——前の置き場に在った物を .stale-a<試行> へ退けるのは、呼び出し側が retire_out で"""
    old = pathlib.Path(prev["out_path"])
    item = load_item(prev, b.dir)
    nid = prev["node"]
    suffix = prev["id"][len(nid + (f"[{item['key']}]" if item else "")):]
    n = prev.get("attempts", 1)
    new = emit_instance(b, nid, item, suffix=suffix, attempt=n + 1)
    if "tree_before" in prev:
        new["tree_before"] = prev["tree_before"]
    new["attempt_log"] = (prev.get("attempt_log") or []) + [{"at": new["emitted_at"], "reason": reason,
                                                             "prev_emitted_at": prev["emitted_at"], "prev_out_path": str(old)}]
    return new


def retire_out(old, n):
    """前の試行の置き場に在った物を .stale-a<試行> へ退ける（done は今の試行の置き場しか読まない）"""
    old = pathlib.Path(old)
    if old.is_file():
        old.replace(old.with_name(old.name + f".stale-a{n}"))


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
    graph_notes = check_graph(graph, validator)
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
    if a.stop_after_round is not None and a.stop_after_round < 1:
        die(f"--stop-after-round は 1 以上（{a.stop_after_round}）——止める周の番号で、その周の締めの後で止まる")
    fn = hook(rules, "check_inputs")
    if fn:
        fn(inputs)   # ループ固有の入力の値（flow・gates 等）は置き場を作る前に確かめる——拒んでも空の盤面を残さない
    bad = choice_input_errors(g, inputs)
    if bad:
        die("; ".join(bad))
    ignored = undeclared_inputs(g, [kv.partition("=")[0] for kv in a.input or []])
    notes = graph_notes + [f"--input {k}=… は graph の inputs に宣言が無く、どの節も rules も読まない（効かない）——綴りを確かめよ"
                           f"（宣言済みの入力: {', '.join(sorted(g.get('inputs') or {}))}）" for k in ignored]
    for n in notes:
        print(f"注意: {n}", file=sys.stderr)
    d.mkdir(parents=True, exist_ok=False)
    fn = hook(rules, "init_record")
    record = fn(th, decider) if fn else {}
    state = {
        "loop_name": loop, "run_id": run_id, "graph": str(pathlib.Path(graph).resolve()),
        "graph_sha": sha(graph_text(graph)),
        "created": now(), "status": "running", "round": 1, "rounds": [empty_round(1)],
        "thickness": th, "max_rounds": max_rounds_for(g, th), "unattended": bool(a.unattended),
        **({"stop_after_round": a.stop_after_round} if a.stop_after_round is not None else {}),
        "inputs": inputs, "validator": validator, "outputs": {}, "done_ever": {}, "loop": {},
        **({"notes": notes} if notes else {}),
    }
    if getattr(a, "unfenced_delegates", None):
        # 人が run ごとに明示したときだけ、任せ先を sandbox で縛らずに回す側が Agent で起こす（人の決定 2026-09-25）。
        # 外した事実と理由は盤面（state と trace）に残り、next の notes と任せ先の instance（unfenced）に毎回出る
        state["unfenced_delegates"] = {"at": now(), "reason": a.unfenced_delegates}
    write_json(d / "state.json", state)
    write_json(d / "record.json", record)
    with open(d / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": "init", "thickness": th, "decider": decider,
                            **({"unfenced_delegates": state["unfenced_delegates"]} if state.get("unfenced_delegates") else {})},
                           ensure_ascii=False) + "\n")
    fn = hook(rules, "on_init")
    if fn:
        # rules の入口が拒んだ（入力の値の検査など）ら、作った置き場を消してから抜ける——この関数の頭の『die しても空の盤面を
        # 残さない』を rules の入口にも当てる（残すと、拒まれた run を current が拾って既定の流れのまま回った）
        try:
            b = Board(d)
            fn(b, a)
            b.save()
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
    # current は resolve_dir が `<git-dir>/graphloops/*/current` を走査して拾う印なので、**--dir を明示した run では書かない**
    # ——走査範囲の外に書いても誰も読まず、--dir をリポジトリの中に向けると run 自身が作業ツリーを汚す（?? current が立つ）。
    # 書くのは入口が全部通った後（拒まれた run を指したまま残さない）
    if not a.dir:
        (d.parent / "current").write_text(str(d) + "\n", encoding="utf-8")
    print(dump({"dir": str(d), "run_id": run_id, "loop": loop, "thickness": th, "thickness_decider": decider, "max_rounds": state["max_rounds"],
                "validator": validator or ("見つからない（report の前に init --validator で渡すか " + (env_root(g["plugin"]) if g.get("plugin") else "graph の plugin") + "）"),
                "overview": g.get("overview", ""), **({"notes": notes} if notes else {}),
                "next": f"python3 {PLUGIN_ROOT / 'scripts' / 'loop.py'} next --dir {d}"}))
