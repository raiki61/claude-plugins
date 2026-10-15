"""vscode.py（送り終えた PR の /catchup のページを VS Code の窓に開く口）の試験。code も窓も偽物。"""

import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import vscode  # noqa: E402


class OpenPages(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.socks = []
        for i, name in enumerate(("vscode-ipc-old.sock", "vscode-ipc-new.sock")):
            s = self.tmp / name
            s.write_text("")
            os.utime(s, (1000 + i, 1000 + i))
            self.socks.append(str(s))
        self.calls = []

    def run_ok(self, argv, env):
        self.calls.append((argv, env["VSCODE_IPC_HOOK_CLI"]))
        return 0 if env["VSCODE_IPC_HOOK_CLI"].endswith("new.sock") else 1

    def test_page_path_follows_the_catchup_layout(self):
        self.assertEqual(vscode.page_path("o/r", 12, home=self.tmp),
                         self.tmp / ".cache" / "attention" / "catchup" / "o-r" / "12.html")

    def test_all_pages_go_to_every_socket_in_one_call_each(self):
        line = vscode.open_pages(["/p/1.html", "/p/2.html"], env={"TMPDIR": str(self.tmp)}, run=self.run_ok,
                                 which=lambda c: "/bin/code")
        self.assertEqual([s for _, s in self.calls], [self.socks[1], self.socks[0]])   # 新しい順に全部
        self.assertEqual(self.calls[0][0], ["/bin/code", "--reuse-window", "/p/1.html", "/p/2.html"])
        self.assertEqual(line, "/catchup のページ 2 件を VS Code の窓 1 個に開いた")

    def test_flag_no_cli_no_window_and_nothing_to_open(self):
        env = {"TMPDIR": str(self.tmp)}
        self.assertIn("ATTENTION_CATCHUP_OPEN=0", vscode.open_pages(["/p/1.html"], env={**env, "ATTENTION_CATCHUP_OPEN": "0"},
                                                                     run=self.run_ok, which=lambda c: "/bin/code"))
        self.assertIn("code が見つからない", vscode.open_pages(["/p/1.html"], env=env, home=self.tmp, run=self.run_ok,
                                                             which=lambda c: None))
        self.assertIn("繋がっていない", vscode.open_pages(["/p/1.html"], env=env, run=lambda a, e: 1, which=lambda c: "/bin/code"))
        self.assertIsNone(vscode.open_pages([], env=env, run=self.run_ok, which=lambda c: "/bin/code"))
        self.assertEqual(self.calls, [])

    def test_failure_inside_is_swallowed(self):
        def boom(argv, env):
            raise RuntimeError("x")
        line = vscode.open_pages(["/p/1.html"], env={"TMPDIR": str(self.tmp)}, run=boom, which=lambda c: "/bin/code")
        self.assertIn("RuntimeError", line)


if __name__ == "__main__":
    unittest.main()
