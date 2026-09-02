#!/usr/bin/env python3
"""what-am-i-doing.py の判定を、本物のセッション記録に触らず固定の材料で回す。

記録の場所の解決（CLAUDE_CONFIG_DIR と cwd から辿る）まで含めて回すため、
作業用の設定ディレクトリを毎回作って差し替える。"""

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "what-am-i-doing", ROOT / "attention" / "scripts" / "what-am-i-doing.py")
wai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wai)

SESSION = "11111111-2222-3333-4444-555555555555"
T0 = "2026-08-30T01:00:00.000Z"


def ask(text, at=T0):
    return {"type": "user", "promptSource": "typed", "timestamp": at,
            "message": {"content": text}, "sessionId": SESSION}


def tool_result(text="道具の出力"):
    """道具の出力も user レコードとして落ちる。依頼に数えてはいけない。"""
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": text}]}, "sessionId": SESSION}


def reply(text, tools=(), at=T0):
    blocks = [{"type": "text", "text": text}]
    for name, cmd in tools:
        blocks.append({"type": "tool_use", "name": name,
                       "input": ({"command": cmd} if cmd else {})})
    return {"type": "assistant", "timestamp": at,
            "message": {"content": blocks}, "sessionId": SESSION}


def build(tmp, records, title="テストの題"):
    cwd = pathlib.Path(tmp) / "work"
    cwd.mkdir(parents=True, exist_ok=True)
    # macOS の一時ディレクトリは /var → /private/var の symlink。chdir 後に見える
    # cwd は解決済みの方なので、記録の置き場も解決済みのパスから決める
    cwd = cwd.resolve()
    config = pathlib.Path(tmp) / "config"
    folder = config / "projects" / str(cwd).replace("/", "-")
    folder.mkdir(parents=True, exist_ok=True)

    lines = list(records)
    if title:
        lines.append({"type": "ai-title", "aiTitle": title, "sessionId": SESSION})
    (folder / f"{SESSION}.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
        encoding="utf-8")

    os.environ["CLAUDE_CONFIG_DIR"] = str(config)
    os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
    os.chdir(cwd)
    return cwd


def run(argv=()):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        wai.main(list(argv))
    return buf.getvalue()


CASES = {}


def case(name):
    def deco(fn):
        CASES[name] = fn
        return fn
    return deco


@case("pairs")
def _pairs(tmp):
    """依頼と、それに対する返答が対で並ぶ。片方だけでは追いつけない。"""
    build(tmp, [ask("最初のお願い"), reply("承知しました。まず調べます"),
                ask("次のお願い"), reply("直して push しました")])
    return run()


@case("ignores-tool-results")
def _ignores(tmp):
    """道具の出力も user レコードとして落ちる。依頼に数えると往復数が壊れる。"""
    build(tmp, [ask("ほんとうの依頼"), tool_result(), tool_result(),
                reply("やりました")])
    return run()


@case("landmarks")
def _landmarks(tmp):
    """区切りになる操作（コミット・push・テスト）は名前で拾う。"""
    build(tmp, [ask("直して出して"),
                reply("直します", tools=[("Bash", "bash tests/run.sh"),
                                          ("Bash", "git commit -m x && git push")])])
    return run()


@case("tool-counts")
def _tools(tmp):
    """何の道具を何回使ったかを添える。作業の重さの手がかりになる。"""
    build(tmp, [ask("調べて"), reply("調べます", tools=[("Bash", "ls"),
                                                        ("Bash", "cat x"),
                                                        ("WebSearch", None)])])
    return run()


@case("first-reply-only")
def _first_reply(tmp):
    """返答は最初のひとまとまりだけ。全文を並べると記録の写しになる。"""
    build(tmp, [ask("お願い"), reply("さいしょの結論"), reply("あとの続き")])
    out = run()
    # 「出ない」ことは出力の突き合わせでは確かめられないので、判定を印にして出す
    ok = "さいしょの結論" in out and "あとの続き" not in out
    return out + ("\nONLY_FIRST_OK" if ok else "\nONLY_FIRST_NG")


@case("no-title")
def _no_title(tmp):
    build(tmp, [ask("題のないセッションでのお願い"), reply("はい")], title=None)
    return run()


@case("start-time")
def _start(tmp):
    """開始は記録の 1 件目から取る。ファイルの ctime は追記のたび動く。"""
    build(tmp, [ask("ふるいお願い", at="2026-01-05T00:00:00.000Z"), reply("はい")])
    return run()


@case("elide")
def _elide(tmp):
    recs = []
    for i in range(30):
        recs += [ask(f"{i:02d} 番目のお願いです"), reply(f"{i:02d} に答えました")]
    build(tmp, recs)
    return run(["--limit", "9"])


@case("full")
def _full(tmp):
    recs = []
    for i in range(30):
        recs += [ask(f"{i:02d} 番目のお願いです"), reply(f"{i:02d} に答えました")]
    build(tmp, recs)
    return run(["--full"])


@case("missing")
def _missing(tmp):
    cwd = pathlib.Path(tmp) / "empty"
    cwd.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = str(pathlib.Path(tmp) / "nowhere")
    os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
    os.chdir(cwd)
    return run()


@case("dirty-paths")
def _dirty(tmp):
    """git status の行からパスを取るとき、位置で切らない。

    出力全体を strip すると 1 行目の先頭空白が消え、桁で切ると 1 文字欠ける。"""
    stripped = "M deploy/local/README.adoc\n M hack/prune-local-disk.sh\n?? new.txt"
    got = [e["path"] for e in wai.changemap.entries_from_porcelain(stripped)]
    want = ["deploy/local/README.adoc", "hack/prune-local-disk.sh", "new.txt"]
    return ("DIRTY_OK" if got == want else f"DIRTY_NG {got}")


@case("topic")
def _topic(tmp):
    """--topic はその語が出た往復だけを出す（/catchup が番号でない語で呼ばれたときの背骨）。
    大文字小文字は区別せず、返答の冒頭にしか無い語でも当てる。"""
    build(tmp, [ask("A の話"), reply("a に答えた"),
                ask("B の話"), reply("B に答えた"),
                ask("C の話"), reply("了解。A も見た")])
    out = run(["--topic", "A"])
    want = {
        "count": "往復 2 件だけを出す" in out,
        "kept": "A の話" in out and "C の話" in out,
        "dropped": "B の話" not in out,
        "none": "この話題が出た往復は無い" in run(["--topic", "Z"]),
        # 複数の語は 1 つの語句として当てる（語ごとの OR だと「の」でほぼ全部残る）
        "phrase": "往復 1 件だけを出す" in run(["--topic", "A", "の話"]),
    }
    bad = [k for k, v in want.items() if not v]
    return "TOPIC_OK" if not bad else "TOPIC_NG " + ",".join(bad) + "\n" + out


@case("dirty-tree")
def _dirty_tree(tmp):
    """未コミットの変更が木で出る。周辺の追跡ファイルも薄く並び、新規は行頭 +、変更は ~。
    そのまま diff の枠に貼れる形（行頭 1 桁が印）。"""
    import subprocess
    cwd = build(tmp, [ask("木を見せて"), reply("はい")])
    git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=cwd, check=True)
    (cwd / "docs").mkdir()
    (cwd / "src").mkdir()
    for rel, text in (("docs/a.md", "a\n"), ("docs/b.md", "b\n"), ("src/x.py", "x = 1\n")):
        (cwd / rel).write_text(text, encoding="utf-8")
    subprocess.run([*git, "add", "."], cwd=cwd, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=cwd, check=True)
    (cwd / "docs" / "a.md").write_text("a\nmore\n", encoding="utf-8")
    (cwd / "docs" / "new.md").write_text("n\n", encoding="utf-8")
    (cwd / "newdir").mkdir()
    (cwd / "newdir" / "n.txt").write_text("n\n", encoding="utf-8")  # 未追跡の階層は中の file で出る
    out = run()
    lines = out.splitlines()
    want = {
        "root": any(l.startswith(" work/") for l in lines),
        "new": any(l.startswith("+") and l[1:].strip().startswith("new.md") and l.rstrip().endswith("新規") for l in lines),
        "mod": any(l.startswith("~") and l[1:].strip().startswith("a.md") and l.rstrip().endswith("+1") for l in lines),
        "sibling": any(l.startswith(" ") and l.strip() == "b.md" for l in lines),
        "untouched_dir_hidden": not any("src/" in l for l in lines),
        "untracked_dir_expanded": any(l.startswith("+") and l[1:].strip().startswith("n.txt") for l in lines),
        "no_nameless_row": not any(l.startswith("+") and l[1:].strip().startswith("新規") for l in lines),
    }
    bad = [k for k, v in want.items() if not v]
    return "TREE_OK" if not bad else "TREE_NG " + ",".join(bad) + "\n" + out


@case("pick-reference")
def _pick(tmp):
    """立場の対象は、会話で一番呼ばれている番号を最優先にする。

    ブランチから引くと、別件のブランチに居るだけで別の PR を拾う。頻度が同じなら
    後に呼ばれた方（話題は後ろへ動く）。"""
    asks = ["#100 を見て", "#200 も #100 も", "#100 の続き", "#300 やって", "#300 まとめ"]
    got = wai.pick_reference(asks)
    want = ["100", "300", "200"]
    return "PICK_OK" if got == want else f"PICK_NG {got}"


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: what-am-i-doing-case.py <" + "|".join(CASES) + ">")
    # ケースは作業場へ chdir する。戻さずに片づけると、Windows は使用中の
    # ディレクトリを消せず PermissionError で落ちる（windows-latest で実測）
    origin = os.getcwd()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        try:
            print(CASES[sys.argv[1]](tmp))
        finally:
            os.chdir(origin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
