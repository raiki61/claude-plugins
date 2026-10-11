"""節のスクリプトを 1 本起こし、run の置き場（ARTIFACTS_DIR）の下で実際に読み書きしたファイルを測る試験の道具。

  python3 tests/nodeio_probe.py <script.py>   （環境変数 NODEIO_PROBE_LOG に測った物の置き場。ほかの環境はスクリプトにそのまま渡す）

Python の監査の口（sys.addaudithook）で open・os.remove・os.rename の出来事を拾い、ARTIFACTS_DIR からの相対パス（posix）を
{"reads": [...], "writes": [...]} で NODEIO_PROBE_LOG に書く（open の書く形・消す・名を替えるは writes。置き場の外は拾わない）。
スクリプトは `python3 <script.py>` と同じ形（sys.argv・sys.path の頭・__main__）で回し、標準出力・終了コードはそのまま。
子のプロセス（スクリプトが subprocess で起こす物）の読み書きは拾わない。宣言（_meta）に照らすのは呼び手
（test_blk_structure の run_block が scopes.node_io_gaps で）。
"""
import json
import os
import runpy
import sys

LOG_ENV = "NODEIO_PROBE_LOG"
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def main() -> None:
    script = os.path.abspath(sys.argv[1])
    log = os.environ.pop(LOG_ENV)
    root = os.path.realpath(os.environ["ARTIFACTS_DIR"])
    seen = {"reads": set(), "writes": set()}

    def rel(path):
        if path is None or isinstance(path, int):
            return None
        full = os.path.realpath(os.path.join(os.getcwd(), os.fsdecode(path)))
        r = os.path.relpath(full, root)
        return None if r == ".." or r.startswith("../") else r.replace(os.sep, "/")

    def hook(event, args):
        if event == "open":
            path, mode, flags = args
            r = rel(path)
            if r is not None:
                writing = any(c in mode for c in "wax+") if isinstance(mode, str) else bool(flags & _WRITE_FLAGS)
                seen["writes" if writing else "reads"].add(r)
        elif event in ("os.remove", "os.rename"):
            for p in args[:2] if event == "os.rename" else args[:1]:
                r = rel(p)
                if r is not None:
                    seen["writes"].add(r)

    sys.argv = [script, *sys.argv[2:]]
    sys.path[0] = os.path.dirname(script)
    sys.addaudithook(hook)
    try:
        runpy.run_path(script, run_name="__main__")
    finally:
        with open(log, "w", encoding="utf-8") as f:
            json.dump({k: sorted(v) for k, v in seen.items()}, f)


if __name__ == "__main__":
    main()
