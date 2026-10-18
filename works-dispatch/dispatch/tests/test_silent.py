"""壊れた入力・文言の違い・人向けの出力で、黙って結果を変えない（受付 e3915a）。filex と、それを使う読み手の倒れ方。"""

import contextlib
import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

import dispatch
import filex
import gitx
import terms
from nodes import bump, clean, tools, wake


class FileX(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "log.jsonl")

    def test_replace_keeps_the_mode_and_leaves_no_temp_file(self):
        p = os.path.join(self.d, "a.json")
        filex.replace(p, "1")
        os.chmod(p, 0o600)
        filex.replace(p, "2")
        self.assertEqual(pathlib.Path(p).read_text(), "2")
        if os.name != "nt":   # Windows の chmod は読み取り専用の印しか持たず、0o600 は 0o666 と読める（POSIX の権限が無い）
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
        self.assertEqual(os.listdir(self.d), ["a.json"])

    def test_append_line_ends_a_cut_line_before_adding(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"a": 1}\n{"b": ')   # 前に書いた処理が行の途中で落ちた
        filex.append_line(self.path, json.dumps({"c": 3}))
        got = filex.read_jsonl(self.path)
        self.assertEqual(got.rows, [{"a": 1}, {"c": 3}])
        self.assertEqual([b["text"] for b in got.bad], ['{"b":'])

    def test_read_stops_at_a_bad_line_when_asked(self):
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:   # 書く側（filex）と同じ \n の行末で書く（Windows の文字の書きの既定は \r\n に替える）
            f.write('{"a": 1}\n[1]\n{"c": 3}\n{"d"')
        whole = filex.read_jsonl(self.path)
        self.assertEqual(whole.rows, [{"a": 1}, {"c": 3}])
        self.assertEqual(whole.pos, len(b'{"a": 1}\n[1]\n{"c": 3}\n'))   # 書きかけの行の頭まで
        stopped = filex.read_jsonl(self.path, stop=True)
        self.assertEqual((stopped.rows, stopped.pos), ([{"a": 1}], len(b'{"a": 1}\n')))
        self.assertIn("list", stopped.bad[0]["why"])
        self.assertEqual(filex.read_jsonl(os.path.join(self.d, "none")).rows, [])

    def test_lock_without_waiting_says_it_is_held(self):
        p = os.path.join(self.d, "x.lock")
        with filex.lock(p) as first:
            self.assertTrue(first)
            out = subprocess.run(
                ["python3", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import filex\n"
                 "with filex.lock(sys.argv[2], wait=False) as got: print(got)", os.path.dirname(filex.__file__), p],
                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


class WakeReads(unittest.TestCase):
    def setUp(self):
        self.inbox = tempfile.mkdtemp()
        self.log = os.path.join(self.inbox, wake.LOG)
        self.place = tempfile.mkdtemp()

    def test_read_new_does_not_move_past_a_bad_line_and_tells_once(self):
        with open(self.log, "w", encoding="utf-8", newline="\n") as f:   # 書く側（filex）と同じ \n の行末で書く（Windows の文字の書きの既定は \r\n に替える）
            f.write('{"to": "co/a"}\nnot json\n{"to": "co/b"}\n')
        rows, pos, bad = wake.read_new(self.log, 0)
        self.assertEqual((rows, pos), ([{"to": "co/a"}], len(b'{"to": "co/a"}\n')))
        self.assertEqual(wake.read_new(self.log, pos)[:2], ([], pos))   # 直すまで先へ進まない
        said = wake._bad_news(self.inbox, self.place, self.log, bad)
        self.assertIn(f"{pos} バイト目の行が読めない", said)
        self.assertEqual(wake._bad_news(self.inbox, self.place, self.log, bad), "")   # 同じ行は 1 度だけ

    def test_a_broken_queue_item_is_skipped_aloud(self):
        d = os.path.join(self.inbox, "q")
        os.makedirs(d)
        pathlib.Path(d, "1.json").write_text('{"id": "a"}', encoding="utf-8")
        pathlib.Path(d, "2.json").write_text('{"id": ', encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual([x["id"] for x in wake.listed(d)], ["a"])
        self.assertIn("2.json が読めない", err.getvalue())


class Attrs(unittest.TestCase):
    def test_worktree_attrs_reads_values_with_newlines(self):
        out = "company.name\n調べ\0company.wait\n一行目\n二行目\0"

        def run(argv, env=None):
            return subprocess.CompletedProcess(argv, 0, out, "")
        self.assertEqual(gitx.worktree_attrs("/x", run), {"name": "調べ", "wait": "一行目\n二行目"})

    def test_broken_json_attrs_stop_the_writers(self):
        bad = {"name": "調べ", "former-names": "[1", clean.LANDED_BRANCHES: '{"b": 1}'}
        with self.assertRaises(gitx.AttrError):
            gitx.former_names(bad, strict=True)
        with self.assertRaises(gitx.AttrError):
            clean.landed_of(bad, strict=True)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual((gitx.former_names(bad), clean.landed_of(bad)), ([], {}))   # 読むだけの道は知らせて空
        self.assertEqual(gitx.former_names({"former-names": '["前"]'}, strict=True), ["前"])


class Schema(unittest.TestCase):
    def test_words_the_check_does_not_read_are_named(self):
        ok = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}
        self.assertEqual(tools.schema_problems(ok), [])
        got = tools.schema_problems({"type": "object", "properties": {"a": {"type": "string", "enum": ["x"]},
                                                                        "b": {"type": "date"}}, "oneOf": []})
        self.assertEqual(got, ["keyword oneOf", "properties.a の keyword enum",
                               "properties.b の type（array・boolean・integer・null・number・object・string のどれか）"])

    def test_a_tool_with_unchecked_words_is_not_run(self):
        tool = {"name": "t", "inputSchema": {"type": "object", "properties": {"a": {"type": "string", "enum": ["x"]}}}}
        found, why = tools.find({"担当": {"tools": [tool]}}, "担当", "t")
        self.assertIsNone(found)
        self.assertIn("enum", why)


class Bump(unittest.TestCase):
    def test_version_is_replaced_only_where_it_is_meant(self):
        text = '{\n  "name": "x",\n  "version": "0.1.0"\n}\n'
        self.assertEqual(bump._set_version("p.json", text, bump._VERSION, "0.2.0", ["version"]),
                         '{\n  "name": "x",\n  "version": "0.2.0"\n}\n')
        # 先に当たる "version" が別の所（依存の版）なら書かずに止める
        nested = '{\n  "deps": {"version": "1.0.0"},\n  "version": "0.1.0"\n}\n'
        with self.assertRaises(bump.BumpError):
            bump._set_version("p.json", nested, bump._VERSION, "0.2.0", ["version"])
        with self.assertRaises(bump.BumpError):
            bump._set_version("p.json", '{"name": "x"}', bump._VERSION, "0.2.0", ["version"])


class SentTimes(unittest.TestCase):
    def test_a_broken_record_is_not_read_as_empty(self):
        d = tempfile.mkdtemp()
        ports = dispatch.Ports()
        self.assertEqual(ports.load_sent(d), {})   # 無ければ空
        pathlib.Path(d, dispatch.SENT_FILE).write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            ports.load_sent(d)   # 空として読むと、次の save_sent が前に送った時刻を全部消す
        ports.save_sent(d, {"pr": 1})
        self.assertEqual(ports.load_sent(d), {"pr": 1})


class Terms(unittest.TestCase):
    def test_a_path_that_cannot_be_read_ends_with_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(terms.main([os.path.join(tempfile.mkdtemp(), "none.md")]), 2)
        self.assertIn("読めない", err.getvalue())


if __name__ == "__main__":
    unittest.main()
