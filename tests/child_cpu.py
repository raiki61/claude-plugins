"""子のプロセスを起動して、終わるまでに使った CPU の秒を返す(gates のフックの「時間内に読み切る」検査が使う)。

その検査が捕まえたいのは、読み方の手数が入力の長さで膨らむ戻り(前は 30 秒・40 秒を超えた形)で、膨らむのは CPU の秒。
壁時計の秒は、同じ機械で別の仕事が CPU を取り合うと伸びる。tests/mutate.py は写しの tests/run.sh を -j 本ずつ並べて走らせるので、
壊していない写し(control)でも waitgate の 20 秒・searchgate の 10 秒を超え、変異のゲートが赤になった
(run 41202847506・41213036540。手元の 1 本だけの回では 5.5 秒)。だから上限は CPU の秒で比べる。

POSIX は終わって回収した子の CPU の秒(getrusage の RUSAGE_CHILDREN。子が回収した孫も入る)の差で測る。Windows は getrusage が
無いので、起動した直後に子のプロセスを開いておき(OpenProcess)、終わった後に GetProcessTimes で読む。
"""

import os
import subprocess
import sys

try:
    import resource
except ImportError:   # Windows
    resource = None


def _children_cpu():
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime


def run(argv, data, env, timeout=None, cwd=None):
    """argv を起動し、data(bytes)を stdin に渡す → (subprocess.CompletedProcess, CPU の秒)。
    timeout は止まらない子を打ち切る壁時計の秒(過ぎたら subprocess.TimeoutExpired)。CPU の上限は呼ぶ側が比べる。
    Windows では子の分だけを数え、子が起動した孫の分は入らない。
    同じプロセスの中で並べて呼ばない(POSIX の差には、間に終わったほかの子の分も入る)。"""
    if resource is not None:
        before = _children_cpu()
        p = subprocess.run(argv, input=data, capture_output=True, env=env, timeout=timeout, cwd=cwd)
        return p, _children_cpu() - before
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                          cwd=cwd) as proc:
        # PROCESS_QUERY_LIMITED_INFORMATION。Popen が子の handle を持っているので、子が先に終わっていても開ける
        h = k32.OpenProcess(0x1000, False, proc.pid)
        if not h:
            proc.kill()
            raise OSError(ctypes.get_last_error(), "子のプロセスを開けない(OpenProcess)")
        try:
            try:
                out, err = proc.communicate(data, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise
            times = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
                raise OSError(ctypes.get_last_error(), "子の CPU の秒を読めない(GetProcessTimes)")
        finally:
            k32.CloseHandle(h)
    # FILETIME は 100 ナノ秒の単位。times の 3 つ目がカーネル、4 つ目がユーザーの時間
    cpu = sum((t.dwHighDateTime << 32 | t.dwLowDateTime) for t in times[2:]) / 1e7
    return subprocess.CompletedProcess(argv, proc.returncode, out, err), cpu


if __name__ == "__main__":
    # 手で確かめる口: python3 tests/child_cpu.py → 1 秒ほど回す子と、1 秒眠る子の CPU の秒と壁時計の秒
    import time
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    for code in ("import time\nt = time.process_time()\nwhile time.process_time() - t < 1: pass", "import time; time.sleep(1)"):
        start = time.monotonic()
        _, cpu = run([sys.executable, "-c", code], b"", dict(os.environ))
        print("CPU %.2f 秒・壁時計 %.2f 秒: %s" % (cpu, time.monotonic() - start, code.splitlines()[-1]))
