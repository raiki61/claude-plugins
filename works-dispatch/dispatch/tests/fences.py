"""設計書のセクション 4 の決まり D1〜D6・D8 と、外のツールの口の決まり D9 を照合するチェック。各関数は照合するルート（`works-dispatch/dispatch` か、試験の一時の木）を受け、誤りの文の一覧を返す。

`tests/` と `vendor/`（attention から写した whose-turn）は照合しない。試験は破った例を字で持ち、写しは正本の決まりに従うため。
字で探すのは D1・D2・D5・D6 だけで、構造の決まり（D3・D4・D9）は Python の構文木で見る。
書く関数は、口を引数で渡されて呼ぶ形（h.run(...)）も名前で数える。字の書き方を変えても逃げられないようにするため。
"""

import ast
import json
import pathlib
import re
import warnings

SKIP = ("tests", "vendor")

# D1: 旧 works（darkfactory）の部品の置き場。darkfactory は新しい工場に置き換わったら外されるので、頼ると一緒に壊れる
OLD_WORKS = (".shared/", "works/dev", "darkfactory", "blk-")

# D4: subprocess を import してよい所（外への口・段の点検 tiers を呼ぶ tierx・whose-turn を呼ぶ prs・始める前の確かめを持つ入口）
# landing.py は入口 dispatch.py の --land の流れを分けた物で、手元の検証のコマンドを回す
# calls.py は入口 dispatch.py の --call と --land の合図の流れを分けた物で、会社の形に書かれたツールのコマンドを回す
# installed.py は入口 dispatch.py が前の版の置き場で打たれたとき、今入っている版の dispatch.py を起動する
# orders.py は入口 dispatch.py の --ask・--deliver の流れを分けた物で、会社の形に書かれた頼みと納品の検査（ask_check・deliver_check）のコマンドを回す
# limit_hook.py は上限で止まった会話から切り離して --move を起動する（会話の子として待たない）
# wake_hook.py は終わりと印した（--done）部署の会話から切り離して --retire を起動する（同じく、会話を止めるので子として待たない）
# limits_entry.py は herdr のタブバーが呼ぶ版に依らない入口で、今入っている版の limits.py を起動する（limits_dir に写して動くので、ほかを import しない）
# wiring.py は入口の口の束（Ports）を組み立てる所で、始める前の確かめが作業場のシェルを起動して読む
SUBPROCESS_OK = {"herdr.py", "gitx.py", "claudex.py", "ghx.py", "vscode.py", "tierx.py", "nodes/prs.py", "dispatch.py", "landing.py",
                 "calls.py", "installed.py", "orders.py", "limit_hook.py", "wake_hook.py", "limits_entry.py", "wiring.py"}
# D4: 外に書く関数（herdr・git・gh の口が持つ）と、それを呼んでよいノード。口を引数で渡されて呼ぶ形（h.run(...)）も数える。
# 口そのもの（herdr.py・gitx.py・ghx.py）は定義する側なので照合しない。subprocess.run は herdr の run ではないので数えない
WRITES = {
    # herdr: 会話を起動する・送る
    "run": {"nodes/launch.py"},
    "rename_pane": {"nodes/launch.py", "nodes/sync.py"},
    "rename_workspace": {"nodes/sync.py"},
    "report_pane_metadata": {"nodes/sync.py"},
    "report_workspace_metadata": {"nodes/sync.py"},
    "move_workspace": {"nodes/sync.py"},   # 部署の作業場を仕事の流れの順に並べる
    "prompt": {"nodes/turn.py", "nodes/deliver.py", "nodes/land.py", "nodes/refresh.py"},
    "send_keys": {"nodes/launch.py", "nodes/deliver.py"},   # launch は止まった attach を Ctrl-C で終わらせ、deliver は残った文に Enter を足す   # deliver は頼みと納品の 1 行を、land はリベースと赤の頼みを窓に送る、refresh は古い版の会話の窓に /reload-plugins を打つ
    # herdr: ブランチの場所（元の clone の git worktree）を作る・開く・消す、作業場を畳む
    "create_worktree": {"nodes/provision.py"},
    "open_worktree": {"nodes/provision.py"},
    "remove_worktree": {"nodes/clean.py"},
    "close_workspace": {"nodes/clean.py"},
    # git: origin のブランチを取る・fast-forward する・作者の force-push に揃える・手元のブランチを消す
    "fetch": {"nodes/provision.py", "nodes/land.py"},
    "fast_forward": {"nodes/provision.py"},
    "reset_keep": {"nodes/provision.py"},
    "delete_branch": {"nodes/clean.py"},
    # git: 部署の成果をメインブランチに入れる（ゲートのブランチとメインブランチへ push・ゲートのブランチを消す・手元のメインブランチを fast-forward・版を上げる一時の場所と commit）
    # tools は機械窓口のツールを origin の既定のブランチの中身で走らせる一時の場所を作って消す
    "push": {"nodes/land.py"},
    # git: メインブランチが先に進んだ部署のブランチを、メインブランチに入れるコマンドがリベースして origin に出す
    "rebase": {"nodes/land.py"},
    "rebase_continue": {"nodes/land.py"},
    "rebase_abort": {"nodes/land.py"},
    "add_path": {"nodes/land.py"},
    "push_rebased": {"nodes/land.py"},
    "drop_remote": {"nodes/land.py"},
    "advance_branch": {"nodes/land.py"},
    "add_detached": {"nodes/land.py", "nodes/tools.py"},
    "remove_detached": {"nodes/land.py", "nodes/tools.py"},
    "commit_all": {"nodes/bump.py"},
    "keep_commit": {"nodes/tools.py"},   # 消すツールの場所の、どのブランチにも無い先頭の commit を ref に残す
    # git: 部署の属性（worktree ごとの設定）を書く
    "enable_worktree_config": {"nodes/provision.py"},
    "set_worktree_attr": {"nodes/provision.py"},
    "unset_worktree_attr": {"nodes/provision.py"},
    "drop_copied_attrs": {"nodes/provision.py"},
    "exclude": {"nodes/provision.py"},
    # claude: 裏の会話を消す（claude rm）
    "remove_session": {"nodes/clean.py"},
    # gh: issue にブランチを結ぶ（GitHub にブランチを作る）・メインブランチへの PR を出す
    "issue_develop": {"nodes/provision.py"},
    "create_pr": {"nodes/land.py"},
    # herdr: サイドバーの印
    "report_activity": {"activity.py"},
}
PORTS = {"herdr.py", "gitx.py", "ghx.py", "claudex.py"}

# D6: 持ち主の環境の字
OWNER_ENV = ("raiki61", "claude-code-oauth-", "/Users/")
# 持ち主のアカウントの起動のコマンド（claude-p1 など）。「claude-p」だけで探すと、Claude Code のプラグインの
# 決まったフォルダ名 .claude-plugin まで捕まえるので、後ろに数字が続くものだけを見る
OWNER_COMMAND = re.compile(r"claude-p\d")


def _files(root, pattern):
    root = pathlib.Path(root)
    for p in sorted(root.rglob(pattern)):
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] in SKIP or "__pycache__" in rel.parts:
            continue
        yield rel.as_posix(), p


def _text_hits(root, words, pattern="*.py", fold=False):
    out = []
    for rel, p in _files(root, pattern):
        text = p.read_text(encoding="utf-8")
        hay = text.lower() if fold else text
        for w in words:
            if (w.lower() if fold else w) in hay:
                out.append(f"{rel}: 「{w}」がある")
    return out


def d1_old_works(root):
    return [f"D1 {e}" for e in _text_hits(root, OLD_WORKS)]


def d2_no_sh(root):
    return [f"D2 {rel}: シェルの台本を置かない" for rel, _ in _files(root, "*.sh")]


# D3: ノードが流れを知らないよう、ノードから読んではいけない物。ほかのノードと、流れを持つ側（入口・入口から分けた流れ・フック）
UPWARD = {"dispatch", "orders", "landing", "calls", "move", "reorg", "retire", "starts", "installed"}
# D3 を破っていると分かっていて、まだ直していない読み（ノード, 読む物）。増やさない。直したら消す（消し忘れはチェックが誤りにする）
# - refresh・tree・sync が読むのは、役の名前と並べ方（role）・属性の名前（wake.REST）・起動方法のフィールド
#   （start.parse）で、どれも流れではなく共有の読み取り。ノードの外の共有の置き場に出すまで外す
D3_KNOWN = {("nodes/refresh.py", "role"), ("nodes/refresh.py", "wake"),
            ("nodes/tree.py", "role"), ("nodes/tree.py", "start"), ("nodes/sync.py", "role")}


def _imported(node):
    """import の 1 文が読むモジュールの名前（nodes の中の物は nodes を外した名前）。`from nodes import x`・`import nodes.x`・
    `from . import x` の形も、読む物の名前で返す。"""
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom):
        if node.module in (None, "nodes"):
            return [a.name for a in node.names]
        names = [node.module]
    else:
        return []
    return [n.split(".")[1] if n.startswith("nodes.") else n.split(".")[0] for n in names]


def d3_nodes_blind(root, known=D3_KNOWN):
    nodes = pathlib.Path(root) / "nodes"
    names = {p.stem for p in nodes.glob("*.py")} if nodes.is_dir() else set()
    out, seen = [], set()
    for rel, p in _files(root, "nodes/*.py"):
        me = p.stem
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            for m in _imported(node):
                what = "ほかのノード" if m in names and m != me else "流れを持つ側" if m in UPWARD or m.endswith("_hook") else None
                if what is None:
                    continue
                if (rel, m) in known:
                    seen.add((rel, m))
                    continue
                out.append(f"D3 {rel}: {what} {m} を import している（流れは入口と流れの側だけが持つ）")
    if pathlib.Path(root).joinpath("nodes").is_dir():
        out += [f"D3 {rel}: {m} はもう import していないので、チェックの外す一覧 D3_KNOWN から消す"
                for rel, m in sorted(known - seen) if pathlib.Path(root, rel).is_file()]
    return out


def d4_outward(root):
    out = []
    for rel, p in _files(root, "*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name == "subprocess" for a in node.names) and rel not in SUBPROCESS_OK:
                    out.append(f"D4 {rel}: subprocess を import している（外への口の外）")
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess" and rel not in SUBPROCESS_OK:
                    out.append(f"D4 {rel}: subprocess から import している（外への口の外）")
                if node.module in ("herdr", "gitx", "ghx", "claudex"):
                    for a in node.names:
                        if a.name in WRITES and rel not in WRITES[a.name]:
                            out.append(f"D4 {rel}: 書く関数 {a.name} を取り込んでいる（{sorted(WRITES[a.name])} の外）")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and rel not in PORTS:
                f = node.func
                if f.attr in WRITES and not (isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
                    if rel not in WRITES[f.attr]:
                        out.append(f"D4 {rel}: 書く関数 {f.attr} を呼んでいる（{sorted(WRITES[f.attr])} の外）")
    return out


def d5_no_timeout(root):
    return [f"D5 {e}（こちらから期限を足さない）" for e in _text_hits(root, ("timeout",), fold=True)]


def d6_no_owner_env(root):
    hits = [e for pattern in ("*.py", "*.json") for e in _text_hits(root, OWNER_ENV, pattern)]
    for pattern in ("*.py", "*.json"):
        for rel, p in _files(root, pattern):
            m = OWNER_COMMAND.search(p.read_text(encoding="utf-8"))
            if m:
                hits.append(f"{rel}: 「{m.group(0)}」がある")
    return [f"D6 {e}（持ち主の環境の値は設定で渡す）" for e in hits]


def d8_schemas(root):
    out = []
    for rel, p in _files(root, "schemas/*.json"):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            out.append(f"D8 {rel}: JSON として読めない（{e}）")
            continue
        if s.get("type") != "object" or "schema" not in s.get("required", []):
            out.append(f"D8 {rel}: type が object で、required に schema を持つこと")
    return out


# D9: 移り変わりの激しい外のツール（端末の herdr・会話の Claude Code）の名前は、口（ports.py が束ねるアダプタ）と口の束の組み立て
# （wiring.py）の中だけに書く。口の外（流れ・ノード・フック）は口の名前（ports.term・ports.chat）で呼び、使う人に見せる文はツールの
# 名前を口の NAME で差し込む。数えるのは、名前（変数・関数・属性・引数・import）と文字列（docstring は除く。説明は直さなくても
# 振る舞いが変わらない）のうち、ツールの名前・コマンド・環境変数・フックのフィールドの名前を含む物。設計は
# docs/specs/2026-10-19-ports-design.md
LOCKIN_NAME = re.compile(r"(?i)herdr|claude")
LOCKIN_TEXT = re.compile(
    r"(?i:herdr)|(?<![\w.~/-])claude(?![\w./-])|Claude Code|CLAUDE_[A-Z]|transcript_path|hook_event_name|hookSpecificOutput"
    r"|additionalContext|bgIsolation|installed_plugins|\b(?:SessionStart|UserPromptSubmit|PreToolUse|PostToolUse)\b"
    r"|^/(?:clear|exit|reload-plugins|catchup|compact)\b|❯"
    r"|(?<!\w)\.claude(?!/company|-plugin|\w)")   # 設定のフォルダ（~/.claude・.claude.json）。会社の形 .claude/company.toml と
#   プラグインの置き場 .claude-plugin は、このツールの外の決まりなので数えない
# 口のアダプタと、口の向こうのツールそのものに付ける部品（ツールの名前を知ってよい所）
# - limits.py・limits_entry.py は herdr のタブバーに Claude Code の使用率を出す部品、activity.py は herdr のサイドバーに Claude Code の
#   作業内容を出すフックで、どちらも 2 つのツールをつなぐこと自体が仕事
LOCKIN_OK = {"herdr.py", "claudex.py", "gitx.py", "ghx.py", "tierx.py", "vscode.py", "ports.py", "wiring.py", "limits.py",
             "limits_entry.py", "activity.py"}
# D9 を破っていると分かっていて、まだ口へ移していない所の数（ファイル: 数）。増やさない。減らしたらここも減らす（減らし忘れも
# チェックが誤りにする。D3_KNOWN と同じ扱い）
D9_KNOWN = {
    "config.py": 2,           # 写しの vendor/claude_auth.py（正本はルートの scripts/claude_auth.py。名前は写しの見張りが決める）
    "dispatch.py": 1,         # 設定のフィールドの名前 hide_claude_dir（使う人の設定に書いてあるので名前を替えない）
    "landing.py": 1,          # 同じ
    "nodes/provision.py": 1,  # 同じ
    "nodes/tree.py": 1,       # 会社の形の置き場 .claude/company.toml（works-dispatch が決めた置き場で、使う人のリポジトリに在る）
    "installed.py": 1,        # 前の版の置き場で打たれても動くよう、標準ライブラリしか読まない（口を import できない）
    "shape_hook.py": 1,       # 口を import できなかったときに出す文（口の NAME を読めない）
}


def _docstrings(tree):
    return {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}


def lockin_sites(tree):
    """構文木の中の、外のツールの名前を書いた所の (行, 字) の並び。"""
    docs = _docstrings(tree)
    out = []
    for n in ast.walk(tree):
        names = []
        if isinstance(n, ast.Name):
            names = [n.id]
        elif isinstance(n, ast.Attribute):
            names = [n.attr]
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [n.name]
        elif isinstance(n, ast.arg):
            names = [n.arg]
        elif isinstance(n, ast.keyword) and n.arg:
            names = [n.arg]
        elif isinstance(n, ast.alias):
            names = [n.name, n.asname or ""]
        elif isinstance(n, ast.ImportFrom):
            names = [n.module or ""]
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            if LOCKIN_TEXT.search(n.value):
                out.append((getattr(n, "lineno", 0), n.value[:60]))
            continue
        out += [(getattr(n, "lineno", 0), x) for x in names if x and LOCKIN_NAME.search(x)]
    return out


def lockin_counts(root):
    """口の外のファイルごとの、外のツールの名前を書いた所の数（0 の物は出さない）。"""
    got = {}
    for rel, p in _files(root, "*.py"):
        if rel in LOCKIN_OK:
            continue
        n = len(lockin_sites(ast.parse(p.read_text(encoding="utf-8"))))
        if n:
            got[rel] = n
    return got


def d9_tools_behind_ports(root, known=None):
    known = D9_KNOWN if known is None else known
    got = lockin_counts(root)
    out = []
    for rel in sorted(set(got) | set(known)):
        n, k = got.get(rel, 0), known.get(rel, 0)
        if n > k:
            out.append(f"D9 {rel}: 外のツール（端末・会話）の名前を口の外に {n} か所書いている（知っている数 {k}。"
                       "口の名前 ports.term・ports.chat と NAME で書く。どこかは python3 tests/fences.py --lockin <ファイル>）")
        elif n < k and pathlib.Path(root, rel).is_file():
            out.append(f"D9 {rel}: 外のツールの名前が {k} から {n} に減ったので、チェックの知っている数 D9_KNOWN を {n} に書き直す")
    return out


def compiles_clean(root):
    """Python が警告を出さずに読める（文字列の中の不正なエスケープなど。今は SyntaxWarning で、先の版で SyntaxError になる）。"""
    out = []
    for rel, p in _files(root, "*.py"):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            try:
                compile(p.read_text(encoding="utf-8"), rel, "exec")
            except (SyntaxError, SyntaxWarning) as e:
                out.append(f"{rel}: 警告なしに読めない（{e}）")
    return out


FENCES = (d1_old_works, d2_no_sh, d3_nodes_blind, d4_outward, d5_no_timeout, d6_no_owner_env, d8_schemas, d9_tools_behind_ports,
          compiles_clean)


def check_all(root):
    return [e for f in FENCES for e in f(root)]


if __name__ == "__main__":
    # python3 tests/fences.py --lockin [ファイル…]: D9 が数える所を行ごとに出す（ファイルを省けば、口の外の全部の数）
    import sys
    # 出すパスと語に日本語が混ざりうるので、Windows の既定のコードページ（cp1252 など）に依らず UTF-8 で書く
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    here = pathlib.Path(__file__).resolve().parent.parent
    args = [a for a in sys.argv[1:] if a != "--lockin"]
    if not args:
        for rel, n in sorted(lockin_counts(here).items()):
            print(f"{rel}: {n}")
    for a in args:
        for line, what in lockin_sites(ast.parse(pathlib.Path(a).read_text(encoding="utf-8"))):
            print(f"{a}:{line}: {what!r}")
