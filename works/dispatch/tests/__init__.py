"""dispatch の試験。`works/dispatch` を import の道の頭に入れ、試験から `import config` の形で読めるようにする。

`works/dispatch` はパッケージにしない。各ノードを単独のコマンドとしても走らせるため。
"""

import pathlib
import sys

DISPATCH = pathlib.Path(__file__).resolve().parent.parent
if str(DISPATCH) not in sys.path:
    sys.path.insert(0, str(DISPATCH))
