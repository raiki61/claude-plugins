"""役の指示書を受け手の表と照らす試験の道具（各ブロックの試験が使う）。

- drawn(test, role, text, off=()): ブロックの試験が描いた役の指示書（本物の支度の出力）を表と照らす。本文に現れた宣言済みの見出しは
  その役の行に在り、その役の行の節で本文に現れない物は、入る条件の関数が off（この描きの本文に入らない関数）に在る物だけ
宣言の読み口（支度のモジュールの場所・場所から読む）は core の promptsection に、受け手の表の行は graphmap.receive_rows に在り、ここはそれを使う。
受け手の表の行を工程に結ぶ graphmap.receive_rows が YAML を読む PyYAML は試験の殻 tests/run.sh が渡す。
"""
import pathlib
import re
import string
import sys

sys.dont_write_bytecode = True
CORE = pathlib.Path(__file__).resolve().parents[1] / ".shared" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import graphmap  # noqa: E402
import promptsection  # noqa: E402

PACK = CORE.parents[1]

# 手で書く役の指示書の本文の在り処（描いた本文に同じ見出しが在っても、機械が貼った節とは言えない）
PROMPT_SOURCES = ("blk-*/prompts/**/*.md", "blk-*/rules/**/*.md", "blk-*/commands/**/*.md", ".shared/core/gl-prompts/**/*.md",
                  ".shared/core/graphloops/prompts/**/*.md", ".shared/core/agents/**/*.md", ".shared/borrow/**/*.md",
                  ".shared/core/writerules/*.md")
_TABLE: dict = {}


def _pattern(heading: str):
    """見出しの型（.format の穴を持つ。行を丸ごと占める穴の中身は複数行でもよい）が本文の行の頭から現れるかの正規表現。1 行目に
    記号・空白・穴の外の字が無い型（`### {key}`）はどの見出しにも当たるので照らせず None"""
    head = heading.strip("\n")
    parts = list(string.Formatter().parse(head))
    first = "".join(lit for lit, *_ in parts).split("\n")[0]
    if not first.strip("# "):
        return None
    body = ""
    for k, (lit, field, *_) in enumerate(parts):
        body += re.escape(lit)
        if field is not None:   # 行を丸ごと占める穴は複数行の中身を、行の中の穴は 1 行の中身を受ける
            after = parts[k + 1][0] if k + 1 < len(parts) else ""
            whole = (not lit or lit.endswith("\n")) and (not after or after.startswith("\n"))
            body += "[\\s\\S]*?" if whole else "[^\\n]*?"
    return re.compile(r"(?m)^" + body + r"(?=\n|\Z)")


def _table(pack: pathlib.Path = PACK):
    """(役 → {節の字: 入る条件の関数の集まり}, [(節の字, 正規表現)]): 受け手の表と、照らせる機械が貼る宣言済みの見出し（human の
    無い物。手で書く役の指示書の本文の元（PROMPT_SOURCES）に同じ見出しが在る物は、本文に現れても機械が貼ったとは言えないので外す）"""
    import yaml

    key = pathlib.Path(pack).resolve()
    if key not in _TABLE:
        roles: dict = {}
        for _, _, row in graphmap.receive_rows(key, yaml.safe_load):
            roles.setdefault(row.role, {}).setdefault(str(row.section), set()).add(row.when)
        heads = {str(sec) for p in promptsection.declaring_files(key)
                 for _, sec in promptsection.declared_sections(promptsection.load(key, p)) if not sec.human}
        docs = [p.read_text(encoding="utf-8") for pat in PROMPT_SOURCES for p in sorted(key.glob(pat))]
        _TABLE[key] = (roles, [(h, rx) for h in sorted(heads)
                               if (rx := _pattern(h)) is not None and not any(rx.search(d) for d in docs)])
    return _TABLE[key]


def drawn(test, role: str, text: str, off=()) -> None:
    """役 role の描いた指示書 text を受け手の表と照らす（試験 test の断言で落とす）。off は、この描きの本文に入らない節の入る条件の
    関数の完全な名（この描きで条件が偽の物・包みが本文でなく system prompt に足す物・本文でなく指示書が名指すファイルで渡す物。ファイルの中身を描ける所は text につないで照らす）"""
    roles, heads = _table()
    mine = roles.get(role, {})
    seen = {h for h, rx in heads if rx.search(text)}
    stray = sorted(h.splitlines()[0] for h in seen if h not in mine)
    test.assertEqual(stray, [], f"役 {role} の指示書に、{role} の行の無い宣言済みの見出しが在る")
    checkable = {h for h, _ in heads}
    unseen = sorted(h.splitlines()[0] for h, whens in mine.items() if h in checkable and h not in seen and not whens & set(off))
    test.assertEqual(unseen, [], f"役 {role} の行の節が指示書に無い（この描きで入る条件が偽なら、その関数を off に名指す）")
    named = {w for whens in mine.values() for w in whens}
    test.assertEqual(sorted(set(off) - named), [], f"off に、役 {role} の行の入る条件でない関数がある")
