"""ブロックのスクリプトを子のプロセスで回す試験の入口（tests/test_blk_rejudge.py が使う）。

python rejudge_child.py <スクリプトのパス> [引数…]: rejudge.OPENER を試験の盤面を開く口（表は everything。手本の盤面は
state.works.line を持たない）に差してから、スクリプトを __main__ として回す。スクリプトは .shared/core を sys.path の頭に入れて
import rejudge するので、ここで読み込んだ同じ module（sys.modules）を使う。環境変数・cwd・終了コードは Archon と同じ形のまま
"""
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rejudgekit  # noqa: E402

rejudgekit.rejudge.OPENER = rejudgekit.opener
script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
