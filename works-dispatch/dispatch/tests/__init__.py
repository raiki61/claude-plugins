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

# 試験が作る一時のフォルダとファイルは、回ごとの 1 つの親（ROOT_ENV が指す。OS の一時の置き場の下の dispatch-test-*）の下に作らせ、
# 回の終わりに親ごと消す（2026-11-09 まで、試験が作った dispatch-fake-* などを消さず、/private/tmp に 5 日で 3 万を超えて残った）。
# 並べて回す parallel.py は、子のプロセスを起動する前にこのパッケージを読んで親を作らせ、子に TMPDIR で渡し、終わりに残りを見る（残りが有れば赤）。parallel.py を
# 通さずに unittest で直に回したときは、ここで親を作り、プロセスの終わりに消す。
import atexit
import shutil
import stat
import tempfile
import unittest

ROOT_ENV = "DISPATCH_TEST_TMP"   # 回の一時の親のパス。子のプロセスはこれが在れば親を作らない


def tmp_root():
    """回の一時の親を作り、このプロセスと子のプロセスの一時の置き場（TMPDIR と tempfile.tempdir）をそこへ向ける。作った親のパス。"""
    root = os.path.realpath(tempfile.mkdtemp(prefix="dispatch-test-"))
    os.environ[ROOT_ENV] = os.environ["TMPDIR"] = root
    tempfile.tempdir = root
    return root


def leftovers(root):
    """回の一時の親に残った物（親からの相対パスの並び）。試験の作った物はどれも scratch か with で消えるので、空が正しい。
    multiprocessing が子のプロセスとの通信に作る pymp-*（Linux の既定の forkserver など。消すのはプロセスの終わり）は数えない。"""
    return sorted(n for n in os.listdir(root) if not n.startswith("pymp-")) if os.path.isdir(root) else []


def rmtree(path):
    """path の木を消す。無い物と消せない物は黙って飛ばす（消し残りは parallel.py の残りの検査が赤にする）。shutil.rmtree の ignore_errors と
    違い、Windows で読み取り専用のファイルは書ける印にしてから消し直す（git の objects は読み取り専用で作られ、ignore_errors では消えずに残る。
    2026-11-09 の Windows の CI で、本物の git で作った試験の世界 dispatch-land-* が 147 件残った）。"""
    def again(func, name, err):
        err = err[1] if isinstance(err, tuple) else err   # 3.12 からの onexc は例外、前の onerror は sys.exc_info の組
        if os.name == "nt" and isinstance(err, PermissionError):
            try:
                os.chmod(name, stat.S_IWRITE)
                func(name)
            except OSError:   # 使用中などで消し直しも断られた物は飛ばす（残れば parallel.py の残りの検査が赤にする）
                pass
    shutil.rmtree(path, **{"onexc" if sys.version_info >= (3, 12) else "onerror": again})


# この回の親をこのプロセスが作ったか（子のプロセスと、入れ子の回は作らない。前の回の値が環境に残って親が無ければ作り直す）
OWNED = not os.path.isdir(os.environ.get(ROOT_ENV) or "")
if OWNED:
    ROOT = tmp_root()
    atexit.register(rmtree, ROOT)
else:
    ROOT = tempfile.tempdir = os.environ["TMPDIR"] = os.environ[ROOT_ENV]


def scratch(**kw):
    """一時のフォルダを作り、そのパスを返す（引数は tempfile.mkdtemp と同じ）。今の試験のモジュールが終わるとき（赤でも）消す。
    試験の中で一時のフォルダを作るときは tempfile.mkdtemp を直に呼ばず、これを使う（作った物を消し忘れない）。"""
    path = tempfile.mkdtemp(**kw)
    unittest.addModuleCleanup(rmtree, path)
    return path
