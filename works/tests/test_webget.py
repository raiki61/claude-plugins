"""web の取得と run をまたぐ控え（.shared/core/webget.py）の検査。網には出ない。

- 控え（Store）: 名ごとに 1 本の JSON。schema が揃い、状態が求める物で、取った時刻 at から ttl の内の物だけを返す。書く時は
  一時のファイルに書いて置き換え、書けなければ理由の 1 行を返す（落とさない）。置き場が無い（None）なら読まず・書かない
- 置き場（shared_root）: 包みの家の env が絶対のパスの時だけ、その下の sub。無い・相対なら None（使わない）
- 網に出ない切り替え（is_off）: 値の前後の空白と大小を無視して off の時だけ真
- 転送（SafeRedirect）: https・公の host の名（safe_url）の先にだけ付いていく。http・IP の字は 3xx のまま返す
- 取得（http_get）: 網に届かない時は FetchError（1 行）。期限は持たない
"""
import pathlib
import sys
import tempfile
import unittest
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import webget  # noqa: E402

SCHEMA = "works-test/1"
T = 1_800_000_000.0


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "cache"
        self.store = webget.Store(self.root, SCHEMA, 100.0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_store_put_then_get_within_ttl(self):
        doc = {"schema": SCHEMA, "status": "ok", "body": "x", "at": T}
        self.assertEqual(self.store.put("a.json", doc), "")
        self.assertEqual(self.store.get("a.json", T + 99, ("ok",)), doc)
        self.assertEqual(list(self.root.glob(".tmp-*")), [], "一時のファイルを残さない")

    def test_store_get_expired_is_none(self):
        self.store.put("a.json", {"schema": SCHEMA, "status": "ok", "at": T})
        self.assertIsNone(self.store.get("a.json", T + 100, ("ok",)), "ttl ちょうどは切れ")
        self.assertIsNone(self.store.get("a.json", T - 1, ("ok",)), "先の時刻の控えは使わない")

    def test_store_get_other_schema_or_status_or_time_is_none(self):
        self.store.put("s.json", {"schema": "other/1", "status": "ok", "at": T})
        self.store.put("e.json", {"schema": SCHEMA, "status": "error", "at": T})
        self.store.put("b.json", {"schema": SCHEMA, "status": "ok", "at": True})
        (self.root / "broken.json").write_text("{x", encoding="utf-8")
        for name in ("s.json", "e.json", "b.json", "broken.json", "absent.json"):
            with self.subTest(name=name):
                self.assertIsNone(self.store.get(name, T + 1, ("ok", "not_found")))

    def test_store_get_without_statuses_takes_any_status(self):
        self.store.put("e.json", {"schema": SCHEMA, "status": "error", "at": T})
        self.assertIsNotNone(self.store.get("e.json", T + 1))

    def test_store_names_lists_fresh_docs_only(self):
        """names: 置き場の名のうち get が返す物（schema・状態・期限が揃う）だけ。一時のファイルと読めない物は数えない"""
        self.store.put("b.json", {"schema": SCHEMA, "status": "ok", "at": T})
        self.store.put("a.json", {"schema": SCHEMA, "status": "ok", "at": T})
        self.store.put("old.json", {"schema": SCHEMA, "status": "ok", "at": T - 1000})
        self.store.put("err.json", {"schema": SCHEMA, "status": "error", "at": T})
        (self.root / ".tmp-x.json").write_text("{}", encoding="utf-8")
        (self.root / "bad.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.store.names(T + 1, ("ok",)), ["a.json", "b.json"])
        self.assertEqual(webget.Store(None, SCHEMA, 100.0).names(T), [])
        self.assertEqual(webget.Store(self.root / "none", SCHEMA, 100.0).names(T), [])

    def test_store_put_unwritable_returns_reason(self):
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.root.write_text("a file, not a folder", encoding="utf-8")
        why = self.store.put("a.json", {"schema": SCHEMA, "status": "ok", "at": T})
        self.assertTrue(why.startswith("a.json: "), why)
        self.assertNotIn("\n", why)

    def test_store_without_root_reads_and_writes_nothing(self):
        none = webget.Store(None, SCHEMA, 100.0)
        self.assertEqual(none.put("a.json", {"schema": SCHEMA, "status": "ok", "at": T}), "")
        self.assertIsNone(none.get("a.json", T))
        self.assertFalse(self.root.exists())


class PlaceCase(unittest.TestCase):
    def test_shared_root_only_for_absolute_home(self):
        self.assertEqual(webget.shared_root({webget.SHARED_ENV: "/h/home"}, "sub"), pathlib.Path("/h/home/sub"))
        for env in ({}, {webget.SHARED_ENV: ""}, {webget.SHARED_ENV: "rel/home"}):
            with self.subTest(env=env):
                self.assertIsNone(webget.shared_root(env, "sub"))

    def test_is_off(self):
        for v, want in (("off", True), (" OFF ", True), ("", False), ("on", False), ("0", False)):
            with self.subTest(v=v):
                self.assertEqual(webget.is_off({"SW": v}, "SW"), want)
        self.assertFalse(webget.is_off({}, "SW"))


class FetchCase(unittest.TestCase):
    def test_redirect_to_unsafe_host_is_not_followed(self):
        req = urllib.request.Request("https://pypi.org/pypi/requests/json", headers={"User-Agent": "works-test"})
        h = webget.SafeRedirect()
        self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {}, "https://elsewhere.example/x"))
        for url in ("http://elsewhere.example/x", "https://10.1.2.3/x", "https://localhost/x", "https://intranet/x",
                    "https://u:p@elsewhere.example/x"):
            with self.subTest(url=url):
                self.assertIsNone(h.redirect_request(req, None, 302, "Found", {}, url))

    def test_url_without_host_is_fetch_error(self):
        """網に出る前に落ちる URL（host が無い）も FetchError の 1 行（網には出ない）"""
        with self.assertRaises(webget.FetchError) as cm:
            webget.http_get("https:///x", {}, 10)
        self.assertNotIn("\n", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
