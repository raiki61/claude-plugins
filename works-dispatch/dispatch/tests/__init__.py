"""dispatch の試験。`works-dispatch/dispatch` を import の道の頭に入れ、試験から `import config` の形で読めるようにする。

`works-dispatch/dispatch` はパッケージにしない。各ノードを単独のコマンドとしても走らせるため。
"""

import os
import pathlib
import sys

DISPATCH = pathlib.Path(__file__).resolve().parent.parent
if str(DISPATCH) not in sys.path:
    sys.path.insert(0, str(DISPATCH))

# 試験は、借りるか買うかの部品（rent-or-buy。リポジトリの隣の checkout に在る）に判断の記録を書かせず、値段を取りに行かせない
os.environ.setdefault("RENT_OR_BUY_RECORD", "off")
os.environ.setdefault("RENT_OR_BUY_OFFLINE", "1")
