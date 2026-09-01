#!/usr/bin/env python3
"""whatamidoing.py の判定を、本物のセッション記録に触らず固定の材料で回す。

網に載せるのは「記録 → 出力」の規則だけ。記録の場所の解決（CLAUDE_CONFIG_DIR と
cwd から辿る）まで含めて回すため、作業用の設定ディレクトリを毎回作って差し替える。"""

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
    "whatamidoing", ROOT / "attention" / "scripts" / "whatamidoing.py")
wai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wai)

SESSION = "11111111-2222-3333-4444-555555555555"


def build(tmp, prompts, title="テストの題", first_stamp="2026-08-30T01:02:03.000Z"):
    """記録を組み立てて、その cwd に居る状態を作る。"""
    cwd = pathlib.Path(tmp) / "work"
    cwd.mkdir(parents=True, exist_ok=True)
    # macOS の一時ディレクトリは /var → /private/var の symlink。chdir 後に見える
    # cwd は解決済みの方なので、記録の置き場も解決済みのパスから決める
    cwd = cwd.resolve()
    config = pathlib.Path(tmp) / "config"
    folder = config / "projects" / str(cwd).replace("/", "-")
    folder.mkdir(parents=True, exist_ok=True)

    lines = [{"type": "user", "timestamp": first_stamp}]
    for text in prompts:
        lines.append({"type": "last-prompt", "lastPrompt": text, "sessionId": SESSION})
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


@case("basic")
def _basic(tmp):
    """題と、依頼者の発言の並びがそのまま出る。"""
    build(tmp, ["最初のお願い", "次のお願い"])
    return run()


@case("dedupe-consecutive")
def _dedupe(tmp):
    """同じ発言が leafUuid 違いで何度も落ちるので、連続の重複だけ畳む。"""
    build(tmp, ["おなじことば", "おなじことば", "おなじことば", "ちがうことば"])
    return run()


@case("dedupe-keeps-distant")
def _distant(tmp):
    """離れて出てきた同じ発言は残す。後からもう一度言うことがある。"""
    build(tmp, ["おなじことば", "あいだのことば", "おなじことば"])
    return run()


@case("no-title")
def _no_title(tmp):
    """題が付いていないセッションは、付いていないと言う。"""
    build(tmp, ["題のないセッションでのお願い"], title=None)
    return run()


@case("start-time")
def _start(tmp):
    """開始時刻は記録の 1 件目から取る。ファイルの ctime は追記のたび動く。"""
    build(tmp, ["ふるいセッションのお願い"], first_stamp="2026-01-05T00:00:00.000Z")
    return run()


@case("elide")
def _elide(tmp):
    """上限を超えたら、黙って切らずに省いた件数を書く。"""
    build(tmp, [f"{i:02d} 番目のお願いです" for i in range(30)])
    return run(["--limit", "9"])


@case("full")
def _full(tmp):
    """--full なら省かない。"""
    build(tmp, [f"{i:02d} 番目のお願いです" for i in range(30)])
    return run(["--full"])


@case("missing")
def _missing(tmp):
    """記録が無いディレクトリでは、無いと言って落ちる（黙って空を出さない）。"""
    cwd = pathlib.Path(tmp) / "empty"
    cwd.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = str(pathlib.Path(tmp) / "nowhere")
    os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
    os.chdir(cwd)
    return run()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: whatamidoing-case.py <" + "|".join(CASES) + ">")
    with tempfile.TemporaryDirectory() as tmp:
        print(CASES[sys.argv[1]](tmp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
