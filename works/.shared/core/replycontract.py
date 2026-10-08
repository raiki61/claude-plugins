"""返答の契約（包みの旗 text-reply。adapter.py の頭の 21）: 節の返答の型を Claude Code の返答の道具（StructuredOutput）に
任せず、本流 review-graph（graphloops/engine/role_run.run_role）と同じく、本文で返させ、受け取った後に型を確かめ、合わなければ
同じ会話に理由を返して出し直させる。

**なぜ要るか。** Archon v0.11.1 は節の output_format を SDK の outputFormat にし、SDK 0.3.282 は schema を argv の
`--json-schema` と stdin の initialize の `jsonSchema` の両方で Claude Code に渡す（バンドルの transport と y_t の initialize）。
Claude Code は schema を受けると道具 StructuredOutput を足し（argv に無ければ initialize の schema で足す。2.1.294 の
『Init JSON schema』）、fork で走る skill（/code-review）はその道具を継いで所見をそこへ書いて終わるので、親の節に所見が
届かなかった（0.2.46 の CHANGELOG。拾い戻しは diverted.py）。Archon は Claude を型を強いる provider と数えて出し直さず
（dag-executor の maxReasks が 0）、structured_output が無ければ節を落とす。

**どうするか（包みの側）。** 旗の起動は argv の `--json-schema` と initialize の `jsonSchema` を外し（子にも fork にも返答の
道具が無い）、返答の形（instruction）を system prompt に足す。子の result の本文を check で読んで確かめ、合わなければ子の
stdin（SDK は文字列の指示文の問い合わせを 1 手と数え、最初の result を見るまで stdin を閉じない。バンドルの
isSingleUserTurn）に理由の user の行を足して同じ会話で出し直させ（REASKS 回まで）、合えば result に structured_output を
置いて Archon へ写す。Archon は今までどおり ajv で確かめ直す（この検査は写しの engine の型検査で、読まない語は Archon だけが見る）。

- instruction(schema):        system prompt に足す返答の形の塊（schema の一番上の印 description は外す）
- strip_init_schema(line):    initialize の行から jsonSchema を外す（ほかの行はそのままのバイト）
- check(text, schema):        (読めた値か None, 型の誤りの一覧。空なら合格)
- unchecked(schema):          check が読まない schema の語（旗の節の schema は空であること。試験が縛る）
- Contract(schema, log):      1 起動の result ごとの決め（on_result）。attach(write, release) で子の stdin につなぐ
"""
import json
import pathlib
import sys
from typing import Callable, List, Optional, Tuple

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:   # 写しの engine（graphloops/engine。L0）
    sys.path.insert(0, str(_GL))

from engine.schema import unknown_keywords, validate_schema  # noqa: E402

# 出し直しの上限。本流 review-graph の graph の launch.resume_on_reject（graphloops/graphs/review-loop.json）と同じ 2。
# 時間の上限は持たない（子の 1 手を待つだけ。持ち主の決め: 期限を足さない）
REASKS = 2
MARK_KEY = "description"   # 一番上の description は包みの印（node_marker）。役には見せない

LEAD = ("返答の形（works の包みより。この節の最後の返答の決まり）: この会話には返答を書く道具（StructuredOutput）が無い。"
        "仕事を終えたら、最後の返答に、下の JSON Schema に合う JSON の object を 1 つだけ地の文で出せ（前後に文を付けない。"
        "``` の囲いも付けない）。包みが受け取って型を確かめ、合わなければ同じ会話で理由を返して出し直させる。"
        "skill・Agent で起こした下請け（fork で走る skill を含む）の答えは、下請けが普段どおり本文で返す物で、この形に"
        "合わせさせない——この決まりはこの節の最上位の会話の最後の返答だけに掛かる。下請けの答えの所見は、この形の中に"
        "写して返せ。")
REASK_NOTE = ("works の包みの受け付けがこの返答を拒んだ。理由:\n{why}\n\n"
              "判定も中身も変えずに形だけ直し、system prompt の『返答の形』の JSON Schema に合う JSON の object を 1 つだけ、"
              "最後の返答に地の文で出し直せ（前後に文を付けない。``` の囲いも付けない）。")


def _shown(schema: dict) -> dict:
    return {k: v for k, v in schema.items() if k != MARK_KEY}


def instruction(schema: dict) -> str:
    """system prompt に足す塊（同じ schema から同じ字。prompt のキャッシュを切らない）"""
    return LEAD + "\n\nJSON Schema:\n" + json.dumps(_shown(schema), ensure_ascii=False)


def strip_init_schema(line: bytes) -> bytes:
    """SDK の initialize の control_request の行なら jsonSchema を外した行、ほかはそのままのバイト"""
    try:
        d = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return line
    req = d.get("request") if isinstance(d, dict) and d.get("type") == "control_request" else None
    if not (isinstance(req, dict) and req.get("subtype") == "initialize" and "jsonSchema" in req):
        return line
    out = dict(d, request={k: v for k, v in req.items() if k != "jsonSchema"})
    return json.dumps(out, ensure_ascii=False).encode("utf-8")


def _candidates(text: str):
    """本流 commands._json_candidates と同じ順: 全文 → 本文中の ``` 囲いの中 → 最初の { から最後の } まで（正規表現を使わない）"""
    yield text
    fence = text.find("```")
    if fence != -1:
        body = text[fence + 3:]
        if body[:4].lower() == "json":
            body = body[4:]
        close = body.find("```")
        if close != -1:
            yield body[:close].strip()
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        yield text[s:e + 1]


def check(text, schema: dict) -> Tuple[object, List[str]]:
    """(読めた値か None, 型の誤り)。値は最初に JSON として読めた候補。誤りが空なら合格"""
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        return None, ["返答の本文が空（最後の返答に JSON の object を出していない）"]
    tried = []
    for cand in _candidates(text):
        if cand in tried:
            continue
        tried.append(cand)
        try:
            value = json.loads(cand)
        except ValueError:
            continue
        return value, validate_schema(value, schema)
    return None, ["返答の本文が JSON として読めない（全文・``` の囲いの中・最初の { から最後の } まで、のどれも）"]


def unchecked(schema: dict) -> List[str]:
    """check が読まない schema の語（写しの engine の型検査の外。Archon の ajv だけが見る）"""
    return unknown_keywords(schema)


def user_line(text: str) -> bytes:
    """SDK が文字列の指示文で書く user の行と同じ形（バンドルの Ejn）"""
    return (json.dumps({"type": "user", "session_id": "", "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                        "parent_tool_use_id": None}, ensure_ascii=False) + "\n").encode("utf-8")


class Contract:
    """1 起動の返答の契約。on_result(result の doc) は Archon へ写す doc（structured_output を置いた写し・そのまま）か、
    持って出し直させた時は None。attach(write, release): write(bytes) は子の stdin に 1 行を書き（書けたら真）、release() は
    決まった（もう出し直さない）ことを stdin の口に知らせる（SDK が stdin を閉じていれば子の stdin も閉じる）。
    log(row) は回ごとの記録 {kind: accepted|reasked|gave_up|error|native, turn, errors?}"""

    def __init__(self, schema: dict, reasks: int = REASKS, log: Optional[Callable[[dict], None]] = None) -> None:
        self.schema = schema
        self.reasks = reasks
        self.asked = 0
        self.log = log or (lambda row: None)
        self.write: Callable[[bytes], bool] = lambda data: False
        self.release: Callable[[], None] = lambda: None

    def attach(self, write: Callable[[bytes], bool], release: Callable[[], None]) -> None:
        self.write, self.release = write, release

    def _done(self, kind: str, doc: dict, **row) -> dict:
        self.log({"kind": kind, "turn": self.asked + 1, **row})
        self.release()
        return doc

    def on_result(self, doc: dict) -> Optional[dict]:
        if "structured_output" in doc:   # 返答の道具が残っていた（schema を外し損ねた）。大きく残して写す
            return self._done("native", doc)
        if doc.get("is_error") or doc.get("subtype", "success") != "success":
            return self._done("error", doc, subtype=doc.get("subtype"))
        value, errs = check(doc.get("result"), self.schema)
        if not errs:
            return self._done("accepted", dict(doc, structured_output=value))
        if self.asked < self.reasks and self.write(user_line(REASK_NOTE.format(why="\n".join(f"- {e}" for e in errs[:20])))):
            self.asked += 1
            self.log({"kind": "reasked", "turn": self.asked, "errors": errs[:20]})
            return None
        # 上限か、子へ書けない: 最後の返答を写して Archon の検査に任せる（読めた値は置き、Archon の ajv が拒めば節が落ちる）
        return self._done("gave_up", doc if value is None else dict(doc, structured_output=value), errors=errs[:20])
