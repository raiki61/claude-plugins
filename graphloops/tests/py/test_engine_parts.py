"""engine の部品を直に呼ぶ小さい検査（S2b で tests/simulate.py の test_units の描画と上限・test_set_path・test_parse_output・
test_threshold_boundaries の③から移した。台本の check 1 件をテスト 1 件に写し、対応は MIGRATION.md）。

型検査の部分（test_units の enum・const・minLength・maxLength）は test_schema.py、読了の標本の閾値（test_threshold_boundaries の
①②）は test_research_rules.py に在る。"""
import json
import time

import pytest

from engine.advance import ITEM_INLINE, slim_item
from engine.commands import parse_output
from engine.render import ABSENT, FILE_CAP, ReadsViolation, Renderer, cap_bytes
from engine.util import Reject, del_path, dump, get_path, set_path

pytestmark = pytest.mark.small


# --- 描画の遮断と貼る上限（test_units から）
def renderer():
    return Renderer({"a": {"b": 1}, "secret": "x"}, reads=["a"])


def test_reads_hole_is_filled():
    assert renderer().render("{{a.b}}") == "1"


def test_hole_outside_reads_raises_even_when_optional():
    """reads に無い穴は optional（{{?…}}）でも空で通さない——遮断が ? 一文字で外れない。KeyError と別の型"""
    with pytest.raises(ReadsViolation):
        renderer().render("{{?secret}}")


def test_missing_optional_hole_is_filled_with_a_word():
    """『無い』は空でなく語で埋める。空に潰すと、文の途中の穴が判定不能の文になり、「この周には無い」と「engine が渡し損ねた」が
    同じ値になる（実測 2026-09-13: p2.diagnose.md の {{?loop.escalated}} が空に潰れた）"""
    assert renderer().render("{{?a.nope}}") == ABSENT


def test_missing_optional_hole_mid_sentence_keeps_the_word():
    assert renderer().render("前は {{?a.nope}} だった") == f"前は {ABSENT} だった"


def test_cap_is_in_bytes():
    """貼る上限はバイト（日本語は 1 字 3 バイト——字数で測ると 2〜3 倍のバイトが通る）"""
    tr = []
    ja = "あ" * (FILE_CAP // 2)
    out = cap_bytes(ja, "x", tr)
    assert len(out.encode()) <= FILE_CAP + 200 and tr, f"{len(ja)} 字＝{len(ja.encode())} バイトを切った"


def test_under_cap_is_unchanged():
    assert cap_bytes("abc", "x", []) == "abc"


# --- 扇の項目を items/ へ出す大きさ（len(dump(slim)) > ITEM_INLINE）——ちょうどは「残す」側（test_threshold_boundaries の③から）
def slim_len(pad):
    slim, omitted = slim_item({"key": "K", "v": "x" * pad})
    return len(dump(slim).encode("utf-8")), omitted


def exact_pad():
    pad = 1
    while slim_len(pad)[0] < ITEM_INLINE:
        pad += 1
    return pad


def test_item_exactly_inline_limit_is_kept():
    n, omitted = slim_len(exact_pad())
    assert n == ITEM_INLINE and not omitted, f"{n} バイト・落とした欄 {omitted}（> と >= の取り違えがここで出る）"


def test_item_one_byte_over_inline_limit_drops_the_field():
    n, omitted = slim_len(exact_pad() + 1)
    assert omitted == ["v"], f"{n} バイト・落とした欄 {omitted}"


# --- 手当ての口（set_path・del_path）は読める綴りだけを受けて、当たらないなら落ちる（test_set_path から）。
# set_path が get_path の読む `a.2.b` を解さなかったとき、`questions[1]` がその名前の鍵を新設して patch が ok を返した
# ——当たっていない手当てが成功と報告された（実測 2026-09-16）。倒れる向きが危ない側なので、書けない綴りは黙って別の場所を作らず落とす
def board():
    return {"questions": [{"k": 0}, {"k": 1}], "a": {"b": {"c": 1}}}


def test_set_path_writes_list_element_by_dotted_index():
    d = board()
    set_path(d, "questions.1", {"k": "書けた"})
    assert d["questions"][1] == {"k": "書けた"}


def test_set_path_walks_into_list_element_keys():
    d = board()
    set_path(d, "questions.0.k", "深い所")
    assert d["questions"][0]["k"] == "深い所"


def test_get_path_reads_what_set_path_wrote():
    d = board()
    set_path(d, "questions.0.k", "深い所")
    assert get_path(d, "questions.0.k") == "深い所"


@pytest.mark.parametrize("bad", ["questions[1]", "questions.9", "questions.1.k.deep"])
def test_set_path_refuses_unwritable_spelling(bad):
    with pytest.raises(KeyError):
        set_path(board(), bad, "x")


def test_bracket_spelling_does_not_create_a_key():
    d = board()
    with pytest.raises(KeyError):
        set_path(d, "questions[1]", "x")
    assert "questions[1]" not in d


def test_set_path_creates_one_leaf_under_existing_dict():
    """葉の新設（作成枝）。腕が無かったとき、作成枝を丸ごと KeyError に差し替える 1 行の退行が一式を緑のまま通った（実測 2026-09-16）"""
    d = board()
    set_path(d, "materials.local_review", {"status": "clean"})
    assert get_path(d, "materials.local_review") == {"status": "clean"}


def dotted_key_board():
    """点を含む鍵が最後に来る綴り。走査が最後の区切りを候補から外していたとき、`outputs["p1.local_review"]` を指す綴りが
    `outputs["p1"]["local_review"]` を黙って新設し、get_path は元の場所を読み続けた（実測 2026-09-16）"""
    d = board()
    d["outputs"] = {"p1.local_review": {"round": 1}}
    set_path(d, "outputs.p1.local_review", {"round": 2})
    return d


def test_set_path_eats_dotted_key_longest_first():
    assert dotted_key_board()["outputs"] == {"p1.local_review": {"round": 2}}


def test_get_path_reads_dotted_key_set_path_wrote():
    assert get_path(dotted_key_board(), "outputs.p1.local_review") == {"round": 2}


def test_set_path_refuses_creating_two_levels():
    """2 段以上の新設は「点を含む 1 つの鍵」と区別が付かないので受けない（どちらの読みも成り立つ綴りを機械が選ばない）"""
    with pytest.raises(KeyError, match="葉とその親の 1 段まで"):
        set_path(dotted_key_board(), "outputs.p2.nope.deep", "x")


def test_refused_two_level_spelling_writes_nothing():
    d = dotted_key_board()
    with pytest.raises(KeyError):
        set_path(d, "outputs.p2.nope.deep", "x")
    assert "p2" not in d["outputs"]


def test_del_path_eats_dotted_key_longest_first():
    d = dotted_key_board()
    del_path(d, "outputs.p1.local_review")
    assert d["outputs"] == {}


@pytest.mark.parametrize("bad", ["outputs.nope", "questions.0", "a.b.nope.deep"])
def test_del_path_refuses_undeletable_spelling(bad):
    """無い鍵・リストの要素・辿れない親"""
    d = dotted_key_board()
    del_path(d, "outputs.p1.local_review")
    with pytest.raises(KeyError):
        del_path(d, bad)


def test_refused_deletes_delete_nothing():
    d = dotted_key_board()
    del_path(d, "outputs.p1.local_review")
    for bad in ("outputs.nope", "questions.0", "a.b.nope.deep"):
        with pytest.raises(KeyError):
            del_path(d, bad)
    assert len(d["questions"]) == 2 and d["a"] == {"b": {"c": 1}}


# --- done が読む返答の剥がし方（test_parse_output から）。**素の JSON を先に読む**——先に囲いを探すと、本文の中の ``` を囲いと
# 誤認して中身を切り出し、正しい返答が『JSON として読めない』で拒まれる（実測 2026-09-12: 指摘文に ```json を書いた runner の返答が落ちた）
INNER = {"findings": [{"where": "x", "text": "実物は ```json … ``` で囲んで返す。正規表現 ```(?:json)?\\s*(.*?)``` は常に不一致"}]}
BARE = json.dumps(INNER, ensure_ascii=False)


def test_bare_json_with_fences_inside_reads_as_is():
    assert parse_output(BARE) == INNER


def test_whole_reply_in_json_fence_is_unwrapped():
    assert parse_output("```json\n" + BARE + "\n```") == INNER


def test_fence_with_prose_around_is_read():
    assert parse_output("以下が返答です。\n```\n" + BARE + "\n```\n以上。") == INNER


def test_reply_without_json_is_rejected():
    with pytest.raises(Reject):
        parse_output("これは JSON ではない")


def broken_fence_message():
    """拒否の文は原因を 1 つに断定しない。候補は素の str で元テキストのどこから切ったかを運ばないので、pos を候補間で比べても
    「どこまで読めたか」にならない（実測 2026-09-15）"""
    broken = '{"findings": [{"where": "配列（"/code-review high" 等）", "text": "x"}]}'
    with pytest.raises(Reject) as e:
        parse_output("```json\n" + broken + "\n```")
    return str(e.value)


def test_rejection_says_how_many_distinct_candidates_were_tried():
    assert "候補 2 本すべてで失敗" in broken_fence_message()


def test_rejection_lists_what_each_cut_did():
    msg = broken_fence_message()
    assert "``` 囲いの中" in msg and "全文そのまま" in msg


def test_rejection_shows_the_broken_value_in_context():
    msg = broken_fence_message()
    assert "/code-review high" in msg and "[ここ]" in msg


def diag_lines(msg):
    return [line for line in msg.splitlines() if line.startswith("  - ")]


def test_diagnostic_lines_match_candidates_tried():
    """『断定しない』は綴りの不在で測れない（別綴りの断定文を注入した写しが全件緑だった。実測 2026-09-16）。名乗った範囲を測れる形
    ＝診断行が候補の数だけ並ぶ構造で見る"""
    assert len(diag_lines(broken_fence_message())) == 2


def test_same_candidate_is_not_tried_twice():
    diag = diag_lines(broken_fence_message())
    assert len(set(diag)) == len(diag)


def test_rejection_carries_advice():
    """助言行が付く（役に直し方を教える側——診断だけ出して直し方を出さない形にしない）"""
    msg = broken_fence_message()
    assert "よくある原因:" in msg and "囲い（```）が閉じていない" in msg


def short_broken_line():
    """省略記号は「まだ前後がある」の印。端で無条件に付けると、無いものが在るように読める"""
    with pytest.raises(Reject) as e:
        parse_output('{"a": "x（"y"）"}')          # 折れる位置が先頭近くで、後ろも短い
    return diag_lines(str(e.value))[0]


def test_no_leading_ellipsis_when_break_is_near_the_start():
    assert "...[ここ]" not in short_broken_line()


def test_no_trailing_ellipsis_when_nothing_follows():
    assert not short_broken_line().rstrip().endswith("...")


def test_third_candidate_label_shows_when_it_is_the_cut_that_failed():
    """3 本目の候補（{ から } まで）は、囲いの外に波括弧が在る形でだけ相異なる中身になる"""
    with pytest.raises(Reject) as e:
        parse_output("前置き { \"a\": } 後書き")
    assert "{ から } まで" in str(e.value)


def test_prose_with_braces_shows_whole_text_failed_from_the_start():
    with pytest.raises(Reject) as e:
        parse_output("これは JSON を返しません。{ここは例です}")
    assert "全文そのまま: Expecting value" in str(e.value)


# 空は候補を出す前に落とす（候補は無条件に全文を 1 本出すので、後ろで「候補が 0 本」を見る枝は到達しない。実測 2026-09-15）
@pytest.mark.parametrize("empty", ["", "   ", "\n\n"], ids=["empty", "spaces", "newlines"])
def test_empty_reply_says_only_that_it_is_empty(empty):
    with pytest.raises(Reject) as e:
        parse_output(empty)
    msg = str(e.value)
    assert "空か空白だけ" in msg and "候補" not in msg


@pytest.mark.parametrize("empty", ["", "   ", "\n\n"], ids=["empty", "spaces", "newlines"])
def test_empty_reply_does_not_name_one_input(empty):
    """読み元を名指しさせない。cmd_done は --output / --stdin / out_path の 3 入口で text を作り、parse_output には text しか
    渡らない。1 つに決め打つと、既定の導線で誤った場所を直しに行かせる"""
    with pytest.raises(Reject) as e:
        parse_output(empty)
    msg = str(e.value)
    assert "out_path" not in msg and "--stdin" not in msg


def test_unclosed_fence_fails_in_linear_time():
    """閉じ ``` が無い返答は、入力長に対して線形で落ちる（以前は正規表現の後戻りで二次になり、空白 80,000 文字で 21.8 秒。
    実測 2026-09-16）。時間を測る検査は環境差で揺れるので、閾値は桁で置く"""
    s = time.time()
    with pytest.raises(Reject):
        parse_output("```json" + " " * 80000 + "x")
    assert time.time() - s < 1.0
