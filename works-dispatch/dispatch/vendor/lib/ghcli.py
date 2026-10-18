"""gh を呼ぶ共通部。/whose-turn と /catchup で共用。

gh(*args) は、gh の標準出力を返す。gh が無い・失敗した・返らないときは、理由の 1 行で止める（sys.exit）。
GraphQL の 504 は過負荷のときに単発で出る（実測）ので、1 回だけやり直し、2 回目も落ちたら止める。返らないのも同じ扱いにする。
graphql_errors=True のときだけ、GraphQL のエラー（gh は本文の JSON を標準出力に出して非 0 で終わる。cli/cli の pkg/cmd/api の
processResponse）を止めずに本文で返す——呼ぶ側が errors を読んで決める（フィールドの無い GitHub で別の問い合わせに取り直すなど）。
"""

# この本文は複数のプラグインに写しで在る。正本は attention/scripts/lib/ghcli.py、写しは works-dispatch/dispatch/vendor/lib/ghcli.py。
# 直すのは正本だけで、配るのは python3 scripts/shared-copies.py --sync attention/scripts/lib/ghcli.py。

import json
import shutil
import subprocess
import sys

# 外部コマンドを無制限に待たない（決着済みの規約 issue #5。隣の what-am-i-doing.py と同じ形）
GH_TIMEOUT_SEC = 60


def _has_errors(out):
    try:
        data = json.loads(out)
    except ValueError:
        return False
    return isinstance(data, dict) and bool(data.get("errors"))


def gh(*args, graphql_errors=False):
    exe = shutil.which("gh")
    if not exe:
        sys.exit("gh が見つからない（PATH に通す）")
    for attempt in (1, 2):
        try:
            r = subprocess.run(  # noqa: S603 — gh は which で解決。引数は呼ぶ側のリテラルと番号・GraphQL のカーソルだけ
                # 復号を UTF-8 に固定する。Windows の既定は locale の code page（cp1252 など）で、日本語のタイトルや本文が
                # 化けるか UnicodeDecodeError で落ちる（実測 2026-09-13: CI の windows-latest）
                [exe, *args], capture_output=True, encoding="utf-8", errors="replace",
                timeout=GH_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            # 504 と同じ「単発の過負荷」として、やり直しの腕に相乗りさせる
            if attempt == 2:
                sys.exit(f"gh {' '.join(args[:2])} が {GH_TIMEOUT_SEC} 秒で返らない")
            continue
        if r.returncode == 0:
            return r.stdout
        # 一時的な失敗かは状態だけで先に決める——504 でも gh は本文を標準出力に出すので、本文の errors を先に見ると
        # やり直さずに返る
        if "504" in r.stderr and attempt == 1:
            continue
        if graphql_errors and args[:2] == ("api", "graphql") and _has_errors(r.stdout):
            return r.stdout
        sys.exit(f"gh {' '.join(args[:2])} が失敗: {r.stderr.strip()}")
    return None
