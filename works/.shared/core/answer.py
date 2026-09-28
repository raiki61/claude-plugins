"""人が関所に答える行（関所の文の「答え方」）。層 L1（works の物を何も知らない）。標準ライブラリだけ。

利用者の PATH に archon は無い（起動の殻が隔離した Archon を通して呼ぶ）ので、答えの行は起動した殻が env に置いた頭
（ENV。後ろに `<run-id> continue|stop "<一言>"` を足せばそのまま打てる行）で組む。use.sh は `sh <use.sh> answer <対象>`
（答えた者の記録も殻が残す）、dogfood.sh は隔離した archon.sh の respond を置く。殻の外で回した run は頭が無いので、
打つ前に置き換える穴 HOLE で書く（直に打てない archon の行は書かない）。
use.sh の answer は答えた者を必須にするので、殻は WHO_ENV に答えた者の穴を置き、行の末尾にそれを見せる。

- head(env=None) -> str: 答えの行の頭
- line(run_id, verb, note, env=None) -> str: 打つ行 1 本（verb は continue か stop）
"""
import os

ENV = "WORKS_ANSWER_CMD"
WHO_ENV = "WORKS_ANSWER_WHO"
HOLE = "<答えの殻（use.sh answer <対象リポジトリ>）>"
VERBS = ("continue", "stop")


def head(env=None) -> str:
    got = ((os.environ if env is None else env).get(ENV) or "").strip()
    return got or HOLE


def line(run_id: str, verb: str, note: str, env=None) -> str:
    if verb not in VERBS:
        raise ValueError(f"答えの語は {VERBS} のどれか: {verb!r}")
    who = ((os.environ if env is None else env).get(WHO_ENV) or "").strip()
    return f'{head(env)} {run_id} {verb} "{note}"' + (f' "{who}"' if who else "")
