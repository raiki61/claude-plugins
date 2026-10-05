"""修正の輪の最後の回に止める単位を選ぶ（依頼 242。修正の受け付け blk-fix/scripts/accept.py が 1 か所で呼ぶ）。

決まりは 2 つの道: 最後の回の拒否の行は、(1) 呼び手が結び先の単位 key を渡した行（declared。申し出の行。key が単位の集合に在る時だけ）はその単位に、
(2) それ以外は文が名指す単位に結ぶ（bind）。結べない行は直す義務の全部の単位に結ぶ（理由は unbound_why）。
結び方は Settlement.how に行ごとに残る: declared（(1)）・text（(2)）・unbound（結べず義務の全部）・owed（park_owed）。
結んだ単位から義務の外の単位を引いて残った単位を止め、残らない行は拒否に数えない（absorbed）。止める単位と足跡を共にする
単位も一緒に止める（closure。ファイルは単位ごとに分けて戻せない）。閉包は義務の外の単位を通って広がらない（義務の外の単位の
足跡のうち止める単位と共にしないパスは戻さない）。settle がこれを 1 回で組み、戻すパスも返す。写しの拒否が義務の外の単位に
だけ結んで止める単位が残らない時は、park_owed が義務の残りを全部止める（受けた直しを黙って捨てない）。

語:
- 足跡（footprint）: 単位が今の段で触ったパス（根からの相対）= 返答の行の files ∪ 今の段の輪の状態の単位の files・test_files。
  .archon/（leftovers.ARCHON_PREFIX）の下は入れない（修正役の物でなく、機械も戻さない）
- 届く試験（reach）: 足跡を起点にした impact.map の tests（import と言及を逆に辿って届くテストのファイル）
- 名指す: 文の中に unit_key か unit_key[:60]（写しの受け付けの文の頭）が在る、か、前後がパスの字でない所にパスが在る。
  パスは key を除いた残りの文で探す（key の頭のパスで、その key の単位でない単位に結ばない）
盤面と作業ツリーは書かない（届く試験の地図は cache_dir に書く）。
"""
import os
import posixpath
import re
import sys
from typing import NamedTuple

sys.dont_write_bytecode = True

import impact  # noqa: E402  （.shared/core。変更に当たる試験の選び）
import leftovers  # noqa: E402  （.shared/core。.archon/ の決まり）
import tddloop  # noqa: E402  （同じブロックの lib。輪の状態の読み口）

OUT_ONLY = ("写しの拒否の行が義務の外の単位にだけ結び、写しは受けないので、義務の残りの単位を全部止めた"
            "（受けた直しを黙って捨てない）")
UNBOUND = "行が単位の key も、どの単位の足跡・届く試験のパスも名指さない（直す義務の全部の単位に結んだ）"
SHARED = "止める単位と足跡（今の段で触ったパス）を共にするので一緒に止めた（ファイルは単位ごとに分けて戻せない）: "
SHARED_OUT = "足跡を共にする義務の外の単位の直しも段の頭の木に戻し、控えの patch に移した: "
_PATHLIKE = re.compile(r"(?<![\w./-])(?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z][A-Za-z0-9]*(?![\w/-])")


class Settlement(NamedTuple):
    park: dict      # 止める単位 → 理由の文の列（結べなかった行は文の後に結べなかった訳を添える）
    absorbed: list  # 数えない行の文（義務の外の単位にだけ結んだ）
    unbound: dict   # 結べなかった行の文 → 理由
    files: set      # 戻すパス（閉包の足跡 ∪ 結べなかった行が名指した変わったパス。.archon/ の下は除く）
    how: dict       # 文 → 結び方（declared＝呼び手が結び先を渡した・text＝文の名指し・unbound＝結べず義務の全部・owed＝park_owed）


def _rel(path: str, repo) -> str:
    path = path.strip()
    return posixpath.normpath(os.path.relpath(path, repo) if os.path.isabs(path) else path)


def _ours(path: str) -> bool:
    top = leftovers.ARCHON_PREFIX.rstrip("/")
    return path != top and not path.startswith(leftovers.ARCHON_PREFIX)


def footprint(rows: list, loop_states: list, repo) -> dict:
    """単位の key → 足跡（返答の行 rows の files と、輪の状態のファイル loop_states の単位の files・test_files）"""
    feet = {}

    def add(key, files):
        if isinstance(key, str):
            got = feet.setdefault(key, set())
            got |= {p for f in files or [] if isinstance(f, str) and f.strip() for p in [_rel(f, repo)] if _ours(p)}
    for row in rows:
        if isinstance(row, dict):
            add(row.get("unit_key"), row.get("files"))
    for state in loop_states:
        for key, unit in (tddloop.load_state(state).get("units") or {}).items():
            add(key, [*(unit.get("files") or []), *(unit.get("test_files") or [])])
    return feet


def reach(repo, rev: str, files: set, cache_dir) -> set:
    """足跡 files から届く試験（impact.map の tests）。files が空なら空"""
    if not files:
        return set()
    return set(impact.map(repo, rev=rev, seeds=sorted(files), cache_dir=cache_dir)["tests"])


def _names(text: str, path: str) -> bool:
    """文が path を名指すか（前後がパスの字でない所）"""
    return re.search(rf"(?<![\w./-]){re.escape(path)}(?![\w/-])", text) is not None


def bind(text: str, keys: set, feet: dict, reached: dict) -> set:
    """文が名指す単位: unit_key（か unit_key[:60]）を名指す単位と、key を除いた残りの文が足跡か届く試験のパスを名指す単位の和"""
    hit, rest = set(), text
    for key in sorted(keys, key=len, reverse=True):
        for needle in dict.fromkeys((key, key[:60])):
            if needle in rest:
                hit.add(key)
                rest = rest.replace(needle, " ")
    for key in set(feet) | set(reached):
        if any(_names(rest, p) for p in feet.get(key, set()) | reached.get(key, set())):
            hit.add(key)
    return hit


def unbound_why(text: str) -> str:
    """結べない行の理由の文（文が名指した根からのパスを添える）"""
    paths = list(dict.fromkeys(_PATHLIKE.findall(text)))
    return f"{UNBOUND}（文が名指したパス: {', '.join(paths[:20])}）" if paths else UNBOUND


def closure(keys: set, feet: dict, stop=frozenset()) -> set:
    """keys から、足跡を共にする単位を辿った閉包（keys を含む）。stop の単位は閉包に入るが、そこからは辿らない"""
    out, todo = set(keys), [k for k in keys if k not in stop]
    while todo:
        mine = feet.get(todo.pop(), set())
        for other, theirs in feet.items():
            if other not in out and mine & theirs:
                out.add(other)
                if other not in stop:
                    todo.append(other)
    return out


def settle(texts: list, *, keys: set, feet: dict, reached: dict, owed: set, out_of_duty: set, changed: set,
           declared: dict = None) -> Settlement:
    """最後の回の拒否の行 texts を単位に結び、止める単位・数えない行・結べなかった行・戻すパスを返す（モジュールの頭の決まり）。
    declared（文 → 結び先の単位 key。省略可）に文が在り key が空でなければ、その文は bind を使わずその key に結ぶ
    （申し出の作り手が結び先を構造のまま渡す。足跡を共にする単位は閉包が足す）"""
    park, absorbed, unbound, named, how = {}, [], {}, set(), {}
    for text in texts:
        hit, why = set((declared or {}).get(text) or ()) & keys, text   # 単位でない key は結ばない（bind と同じ集合）
        how[text] = "declared"
        if not hit:   # declared に無い・declared の key が単位の集合に無い文は文の名指しで結ぶ
            hit, how[text] = bind(text, keys, feet, reached), "text"
        if not hit:
            how[text] = "unbound"
            unbound[text] = unbound_why(text)
            named |= {p for p in changed if _names(text, p)}
            hit, why = set(owed), f"{text}（{unbound[text]}）"
        mine = sorted(hit - out_of_duty)
        if not mine:
            absorbed.append(text)
        for key in mine:
            park.setdefault(key, []).append(why)
    return _settled(park, absorbed, unbound, named, feet, out_of_duty, how)


def park_owed(texts: list, *, feet: dict, owed: set, out_of_duty: set) -> Settlement:
    """写しの拒否の行 texts が義務の外の単位にだけ結んで止める単位が残らない時: 行を義務の残り（owed − out_of_duty）の全部に
    結んで止める（理由は文の後に OUT_ONLY）。閉包と戻すパスは settle と同じ"""
    park = {}
    for text in texts:
        for key in sorted(owed - out_of_duty):
            park.setdefault(key, []).append(f"{text}（{OUT_ONLY}）")
    return _settled(park, [], {}, set(), feet, out_of_duty, dict.fromkeys(texts, "owed"))


def _settled(park: dict, absorbed: list, unbound: dict, named: set, feet: dict, out_of_duty: set, how: dict) -> Settlement:
    """止める単位 park に閉包（義務の外の単位は通らない）の単位を足し、戻すパス（義務の外でない閉包の単位の足跡 ∪ named。
    義務の外の単位と止める単位が共にするパスは止める単位の足跡に在る）を添えた Settlement"""
    group = closure(set(park), feet, stop=out_of_duty) if park else set()

    def near(key):
        return sorted(o for o in group if o != key and feet.get(o, set()) & feet.get(key, set()))
    for key in sorted(group - set(park) - out_of_duty):
        park[key] = [f"{SHARED}{near(key)}（共にするパス {sorted(set().union(*(feet[o] for o in near(key))) & feet[key])}）"]
    for key in sorted(group & out_of_duty):
        for p in near(key):
            if p in park:
                park[p].append(f"{SHARED_OUT}{key}（共にするパス {sorted(feet[p] & feet[key])}）")
    files = set().union(*(feet.get(k, set()) for k in group - out_of_duty)) | named
    return Settlement(park, absorbed, unbound, {p for p in files if _ours(p)}, how)
