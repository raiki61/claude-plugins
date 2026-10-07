"""works/dev/graphmap_build.py — 工程の地図の元（入口の YAML の隣の <名>.graph.json）を書く・古さを確かめる（開発の道具）。

  uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py build <pack> [<入口の名>…]
  uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py check <pack> [<入口の名>…]

pack の宣言 archon-plugin.json の entrypoints の入口ごとに、部品 .shared/core/graphmap の build で地図の元を組む（入口の名を
省けば全部）。build は書き、check は書かずに、今の YAML から組んだ物と字で違う（か無い）元を名指して終了コード 1 で抜ける。
YAML を替えたら build で書き直す（包みは古い元の地図を足さない。試験 tests/test_graphmap.py が古い元を赤にする）。
pack の模块は標準ライブラリだけなので、YAML を読む PyYAML はこの道具が渡す。
"""
import pathlib
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / ".shared" / "core"))

import graphmap  # noqa: E402


def main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):   # 場所の設定が ASCII・cp1252 でも日本語の行で落ちない
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in ("build", "check"):
        print("usage: graphmap_build.py build|check <pack> [<入口の名>…]", file=sys.stderr)
        return 2
    import yaml

    pack = pathlib.Path(argv[1]).resolve()
    eps = graphmap.entrypoints(pack)
    names = list(argv[2:]) or sorted(eps)
    unknown = [n for n in names if n not in eps]
    if unknown:
        print(f"graphmap_build: 入口に無い名 {', '.join(unknown)}（在るのは {', '.join(sorted(eps))}）", file=sys.stderr)
        return 2
    resolve = graphmap.pack_resolver(pack, yaml.safe_load)
    bad = 0
    for name in names:
        out = graphmap.graph_path(pack, eps[name])
        text = graphmap.dumps(graphmap.build(pack / eps[name], resolve, pack, yaml.safe_load))
        if argv[0] == "build":
            out.write_text(text, encoding="utf-8")
            print(f"graphmap_build: {out.relative_to(pack)} を書いた")
        elif not out.is_file() or out.read_text(encoding="utf-8") != text:
            print(f"graphmap_build: {out.relative_to(pack)} が古い（graphmap_build.py build {argv[1]} {name} で書き直す）",
                  file=sys.stderr)
            bad = 1
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
