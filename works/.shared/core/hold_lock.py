"""殻が開いた fd を排他の鍵（flock）で取る口。sh には flock が無いので、dev/lib.sh works_dev_continue が続き中の印を持つのに使う。

使い方: python3 hold_lock.py <fd>。鍵は開いたファイルの記述に結ぶので、この子が終わっても fd を開いたままの殻が持ち続ける。
別の持ち手が居て取れなければ BlockingIOError で 0 以外に終わる
"""
import fcntl
import sys

fcntl.flock(int(sys.argv[1]), fcntl.LOCK_EX | fcntl.LOCK_NB)
