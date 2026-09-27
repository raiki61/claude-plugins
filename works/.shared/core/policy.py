"""人の方針の文を役に届ける形に組む（線 A の仕様 3.1・8 節。裁定 TA10）。

方針の文書の置き場を決めて写しを固定するのは、盤面を作る時の写しの RL の on_init（policy_input.resolve。共通の git の置き場の
graphloops/policy.md か、入力 policy_md で名指した文書を、盤面の policy/<sha256>.md に写し、record.process.policy に
{path, sha256, copy} を置く）。ここはその写しから、start がブロックの入力（policy_paste・policy_path）に渡す物を組むだけ。

- PASTE_CAP: 貼る本文の上限（バイト）。engine が役に貼る本文の上限 FILE_CAP（engine/render.py）と同じ値を引く
- brief(board): {"paste": 貼る本文, "path": 写しの置き場}。方針の文書が無ければ両方空。上限を超えたら先頭を切り、
  続きの置き場を末尾に書く（切った後の全体が上限の内）
"""
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import board  # noqa: E402,F401  （写しの graphloops を sys.path に足す）
from engine.render import FILE_CAP  # noqa: E402

PASTE_CAP = FILE_CAP   # 40000。engine の役に貼る本文の上限と同じ（バイトで測る。日本語は字数の約 3 倍）


def brief(b) -> dict:
    """record.process.policy.copy（固定した版の写し）から {paste, path}。写しが無い（方針の文書が無い run）なら両方空"""
    copy = ((b.record.get("process") or {}).get("policy") or {}).get("copy")
    if not copy:
        return {"paste": "", "path": ""}
    data = pathlib.Path(copy).read_bytes()
    if len(data) <= PASTE_CAP:
        return {"paste": data.decode("utf-8", "replace"), "path": copy}
    note = f"\n\n［方針の文書は {len(data)} バイトで、{PASTE_CAP} バイトまでを貼った。続きは {copy}］\n"
    room = PASTE_CAP - len(note.encode("utf-8"))
    head = data[:room].decode("utf-8", "ignore")
    return {"paste": head + note, "path": copy}
