#!/usr/bin/env python3
"""子の claude に認証だけを足して起こす前置。`with-auth.py <コマンド> [引数...]` を受け、
標準入力・標準出力・標準エラーはそのまま子に継がせ、子の終了コードをそのまま返す。

graph の `launch.isolated.via` がこれを argv の前に置く。**認証の段そのものは持たない**
——隣の `claude_auth.py`（複数のプラグインに写しで在る共有の本文）が持つ。ここに在るのは
「前置として起動する」殻だけで、なぜ層が要るか・段がどう決まるかは `claude_auth.py` の冒頭に在る。
"""
import os
import pathlib
import subprocess
import sys

# 標準エラーだけ UTF-8 に固定する。Windows は locale 既定の code page になり（GitHub Actions
# windows-latest で cp1252 を実測。日本語 Windows なら cp932）、日本語の 1 行が
# UnicodeEncodeError でこの層ごと落ちる。標準入出力は触らない——**子に継がせる生の fd** で、
# ここで包み直しても子には効かず、材料（数十万バイト）を無駄に写すだけになる。
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 隣の共有の本文を読む。**`sys.path[0]` に頼らない**——importlib でパスから読み込まれる場（検査）では
# 起動時のディレクトリが入らないので、自分の在り処から明示で足す。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import claude_auth  # noqa: E402


# 起こしてよいコマンドの名前。**この層は claude 専用に狭めてある**——auto mode の分類器は
# 子の claude を起こす形を止める（実測 2026-09-15: 『Auto-Mode Bypass』）ので、回す側の環境には
# この層を名指しする許可ルールを 1 本置くことになる。何でも exec できる層だと、その 1 本が
# 「何でも起こしてよい」の意味になってしまう。名前を縛れば、許可ルールの意味は
# 「claude を認証付きで起こしてよい」に留まる（逃げ道の環境変数は置かない——同じコマンド行で立てられる）。
ALLOWED = ("claude",)


def main(argv):
    if not argv:
        sys.stderr.write("with-auth: 使い方: with-auth.py <claude のパス> [引数...]\n")
        return 2
    name = pathlib.PurePath(argv[0]).name.lower()
    if name.rsplit(".", 1)[0] not in ALLOWED and name not in ALLOWED:
        sys.stderr.write("with-auth: %r は起こせない——この層は %s 専用（許可ルールを広げないため）\n"
                         % (argv[0], "/".join(ALLOWED)))
        return 2
    env, note = claude_auth.auth_env(os.environ, service=os.environ.get("GL_KEYCHAIN_SERVICE"))
    sys.stderr.write("with-auth: auth=%s config-dir=%s\n" % (note, env["CLAUDE_CONFIG_DIR"]))
    if not claude_auth.added(note):
        # 足せなかったことは**起こす前に**分かる。後から出力を覗く作りにはしない
        # ——子の返答は数百 KB になり得て、この層で溜める理由が無い
        sys.stderr.write("with-auth: %s\n" % claude_auth.QUIET_FAILURE_NOTE)
    sys.stderr.flush()
    try:
        rc = subprocess.run(argv, env=env).returncode  # 標準入出力は継がせる（材料をこの層に溜めない）
    except OSError as e:
        sys.stderr.write("with-auth: %r を起こせない（%s）\n" % (argv[0], e))
        return 127
    if rc != 0:
        # 子の出力は回す側が out_path で見る。ここでは「どの段で起こしたか」だけを添える
        sys.stderr.write("with-auth: 子が rc=%d で落ちた。認証は %s ——『login してください』の類なら、"
                         "この config-dir に認証が無いか、足したトークンが古い\n" % (rc, note))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
