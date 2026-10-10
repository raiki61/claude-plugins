"""世界の解の抜き書きの照らしと検索語の検査（blk-world/lib/worldcheck.py。計画 docs/plans/2026-10-09-world-solution.md の W3）。

- 検索語の検査: 依頼の行（where と字）から対象の識別子を集め（banned_tokens）、問題の類・検索語・定石の文に現れたら名指す（text_problems）
- 抜き書きの照らし: 機械が同じ URL を取り直した本文で照らし、本文に字のまま在る抜き書きだけを残す（verify）。
  網の口は偽の get を渡す（網・git・子のプロセスなし）
"""
import inspect
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
for p in (ROOT / ".shared" / "core", ROOT / "blk-world" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import webget  # noqa: E402
import worldcheck  # noqa: E402

URL = "https://example.org/guide/tdd"
OTHER = "https://example.org/other"
PAGE = ("<html><head><title>Guide</title><style>p{color:red}</style><script>var x = 'not text';</script></head>"
        "<body><h1>Red, green, refactor</h1><p>Write a failing test first. A compile error is not a red test:"
        " add the smallest stub so the test runs and fails on the expected assertion.</p></body></html>")
GOOD = "A compile error is not a red test: add the smallest stub so the test runs and fails on the expected assertion."


def getter(pages, calls=None):
    def get(url):
        if calls is not None:
            calls.append(url)
        got = pages[url]
        if isinstance(got, Exception):
            raise got
        return got
    return get


class Normalize(unittest.TestCase):
    def test_html_tags_scripts_and_entities_are_dropped(self):
        got = worldcheck.normalize(b"<p>A&amp;B <b>bold</b></p><script>hidden()</script><style>x{}</style>")
        self.assertEqual(got, "a&b bold")

    def test_width_case_and_spaces_are_folded(self):
        self.assertEqual(worldcheck.normalize("Ｆｕｌｌ  Width\n\tText"), "full width text")

    def test_typographic_quotes_match_plain(self):
        self.assertEqual(worldcheck.normalize("“don’t”"), worldcheck.normalize('"don\'t"'))


class Verify(unittest.TestCase):
    def test_refetch_alone_proves_excerpt(self):
        """照らしは機械が取り直した本文だけで決まる（役の取得の記録を引数に取らない）。本文に字のまま在る抜き書きは、呼び手の行
        （id を含む）のまま残る（照らしは id を付け直さない）"""
        self.assertEqual(list(inspect.signature(worldcheck.verify).parameters), ["excerpts", "get"])
        rows = [{"id": "c1", "url": URL, "excerpt": GOOD}]
        got = worldcheck.verify(rows, getter({URL: (200, PAGE.encode())}))
        self.assertEqual(got["kept"], rows)
        self.assertEqual(got["dropped"], [])

    def test_excerpt_found_in_body_is_kept(self):
        got = worldcheck.verify([{"id": "c1", "url": URL, "excerpt": GOOD}], getter({URL: (200, PAGE.encode())}))
        self.assertEqual([(k["id"], k["url"], k["excerpt"]) for k in got["kept"]], [("c1", URL, GOOD)])
        self.assertEqual(got["dropped"], [])
        self.assertFalse(got["offline"])

    def test_paraphrase_is_dropped(self):
        para = "Compile errors do not count as red; write a minimal stub and then watch it fail properly."
        got = worldcheck.verify([{"id": "c1", "url": URL, "excerpt": para}], getter({URL: (200, PAGE.encode())}))
        self.assertEqual(got["kept"], [])
        self.assertEqual([(d["id"], d["url"]) for d in got["dropped"]], [("c1", URL)])
        self.assertIn("本文に無い", got["dropped"][0]["why"])

    def test_url_not_fetched_by_role_is_dropped(self):
        """役が取得した記録は引かない: どの記録にも無い URL でも、機械が取り直した本文に字のまま在れば残る"""
        calls = []
        got = worldcheck.verify([{"id": "c1", "url": URL, "excerpt": GOOD}], getter({URL: (200, PAGE.encode())}, calls))
        self.assertEqual(len(got["kept"]), 1)
        self.assertEqual(calls, [URL])

    def test_fetched_url_matches_without_fragment_or_trailing_slash(self):
        calls = []
        rows = [{"id": "c1", "url": URL + "#red", "excerpt": GOOD}, {"id": "c2", "url": URL + "/", "excerpt": GOOD}]
        got = worldcheck.verify(rows, getter({URL + "#red": (200, PAGE.encode())}, calls))
        self.assertEqual(calls, [URL + "#red"])
        self.assertEqual(len(got["kept"]), 2)

    def test_short_excerpt_is_dropped(self):
        got = worldcheck.verify([{"id": "c1", "url": URL, "excerpt": "red test"}], getter({URL: (200, PAGE.encode())}))
        self.assertEqual(got["kept"], [])
        self.assertIn(str(worldcheck.MIN_EXCERPT), got["dropped"][0]["why"])

    def test_unsafe_url_is_not_fetched(self):
        calls = []
        bad = "http://localhost/x"
        got = worldcheck.verify([{"id": "c1", "url": bad, "excerpt": GOOD}], getter({}, calls))
        self.assertEqual(got["kept"], [])
        self.assertEqual(calls, [])

    def test_error_status_is_dropped(self):
        got = worldcheck.verify([{"id": "c1", "url": URL, "excerpt": GOOD}], getter({URL: (404, PAGE.encode())}))
        self.assertEqual(got["kept"], [])
        self.assertIn("404", got["dropped"][0]["why"])
        self.assertFalse(got["offline"], "答えが返った取り直しは網に届いている")

    def test_same_url_is_fetched_once(self):
        calls = []
        rows = [{"id": "c1", "url": URL, "excerpt": GOOD}, {"id": "c2", "url": URL, "excerpt": "Write a failing test first."}]
        got = worldcheck.verify(rows, getter({URL: (200, PAGE.encode())}, calls))
        self.assertEqual(calls, [URL])
        self.assertEqual(len(got["kept"]), 2)
        self.assertEqual(len({k["id"] for k in got["kept"]}), 2)

    def test_all_fetch_errors_mark_offline(self):
        down = webget.FetchError("URLError: no route")
        rows = [{"id": "c1", "url": URL, "excerpt": GOOD}, {"id": "c1", "url": OTHER, "excerpt": GOOD}]
        got = worldcheck.verify(rows, getter({URL: down, OTHER: down}))
        self.assertTrue(got["offline"])
        self.assertEqual(got["kept"], [])
        self.assertEqual(len(got["dropped"]), 2)

    def test_one_reachable_fetch_is_not_offline(self):
        down = webget.FetchError("URLError: no route")
        rows = [{"id": "c1", "url": URL, "excerpt": GOOD}, {"id": "c1", "url": OTHER, "excerpt": GOOD}]
        got = worldcheck.verify(rows, getter({URL: (200, PAGE.encode()), OTHER: down}))
        self.assertFalse(got["offline"])

    def test_nothing_to_fetch_is_not_offline(self):
        self.assertFalse(worldcheck.verify([], getter({}))["offline"])


FINDINGS = [
    {"where": "works/.shared/core/gatemarks.py:265", "text": "`purpose_text` に依頼の解き方が写る。WORKS_LIBDOCS_WEB を見よ"},
    {"where": "src/stats.py", "text": "TDD の赤を判定する。blk-judge の run 167e14c3 で落ちた。test_mean_of_three が赤"},
]


class Banned(unittest.TestCase):
    def setUp(self):
        self.banned = worldcheck.banned_tokens(FINDINGS)

    def test_where_paths_and_file_names_are_banned(self):
        for w in ("works/.shared/core/gatemarks.py", "gatemarks.py", ".shared", "stats.py", "src/stats.py"):
            self.assertIn(w, self.banned)

    def test_identifiers_in_text_are_banned(self):
        for w in ("purpose_text", "WORKS_LIBDOCS_WEB", "blk-judge", "167e14c3", "test_mean_of_three"):
            self.assertIn(w, self.banned)

    def test_plain_words_are_not_banned(self):
        for w in ("TDD", "works", "src", "core", "run"):
            self.assertNotIn(w, self.banned)

    def test_query_with_target_identifier_is_refused(self):
        self.assertEqual(worldcheck.text_problems("How should gatemarks.py decide red in TDD", self.banned), ["gatemarks.py"])
        self.assertEqual(worldcheck.text_problems("purpose_text と blk-judge の書き方", self.banned), ["blk-judge", "purpose_text"])

    def test_query_in_the_words_of_the_activity_passes(self):
        self.assertEqual(worldcheck.text_problems("test-first development: what counts as a failing test when the code does"
                                                  " not compile yet", self.banned), [])

    def test_match_is_by_whole_token(self):
        self.assertEqual(worldcheck.text_problems("purpose_text_more gatemarks.pyc", self.banned), [])

    def test_case_is_ignored(self):
        self.assertEqual(worldcheck.text_problems("works_libdocs_web", self.banned), ["WORKS_LIBDOCS_WEB"])

    def test_findings_that_are_not_rows_are_skipped(self):
        self.assertEqual(worldcheck.banned_tokens(["x", {"where": 3}]), set())


if __name__ == "__main__":
    unittest.main()
