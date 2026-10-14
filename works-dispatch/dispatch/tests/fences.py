"""設計書 4 節の決まり D1〜D6・D8 を照らす柵。各関数は照らす根（`works-dispatch/dispatch` か、試験の一時の木）を受け、誤りの文の一覧を返す。

`tests/` と `vendor/`（attention から写した whose-turn）は照らさない。試験は破った例を字で持ち、写しは正本の決まりに従うため。
字で探すのは D1・D2・D5・D6 だけで、構造の決まり（D3・D4）は Python の構文木で見る。
書く関数は、口を引数で渡されて呼ぶ形（h.run(...)）も名前で数える。字の書き方を変えても逃げられないようにするため。
"""

import ast
import json
import pathlib
import re

SKIP = ("tests", "vendor")

# D1: 旧 works（darkfactory）の部品の置き場。darkfactory は新しい工場に置き換わったら外されるので、頼ると一緒に壊れる
OLD_WORKS = (".shared/", "works/dev", "darkfactory", "blk-")

# D4: subprocess を import してよい所（外への口・whose-turn を呼ぶ prs・始める前の確かめを持つ入口）
SUBPROCESS_OK = {"herdr.py", "gitx.py", "claudex.py", "ghx.py", "nodes/prs.py", "dispatch.py"}
# D4: 外に書く関数（herdr と git の口が持つ）と、それを呼んでよいノード。口を引数で渡されて呼ぶ形（h.run(...)）も数える。
# 口そのもの（herdr.py・gitx.py）は定義する側なので照らさない。subprocess.run は herdr の run ではないので数えない
WRITES = {
    "run": {"nodes/launch.py"},
    "prompt": {"nodes/turn.py"},
    "create_workspace": {"nodes/provision.py"},
    "close_workspace": {"nodes/clean.py"},
    "clone": {"nodes/provision.py"},
    "set_origin": {"nodes/provision.py"},
    "fetch": {"nodes/provision.py"},
    "report_activity": {"activity.py"},
}
PORTS = {"herdr.py", "gitx.py"}

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


def d3_nodes_blind(root):
    nodes = pathlib.Path(root) / "nodes"
    names = {p.stem for p in nodes.glob("*.py")} if nodes.is_dir() else set()
    out = []
    for rel, p in _files(root, "nodes/*.py"):
        me = p.stem
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if m in names and m != me:
                    out.append(f"D3 {rel}: ほかのノード {m} を import している（流れは dispatch.py だけが持つ）")
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
                if node.module in ("herdr", "gitx"):
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


FENCES = (d1_old_works, d2_no_sh, d3_nodes_blind, d4_outward, d5_no_timeout, d6_no_owner_env, d8_schemas)


def check_all(root):
    return [e for f in FENCES for e in f(root)]
