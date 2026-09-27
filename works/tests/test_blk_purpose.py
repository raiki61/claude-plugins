"""目的の文のブロック（blk-purpose。graph の節 p0.purpose）の検査。

- YAML の口: 目的の役の節の output_format が写しの graph の型（role_schema("p0.purpose")）と同じか、良い返答の見本が
  それを通るか。入口・出口・輪の形。目的の審査（p0.purpose_review）をこのブロックに入れず、線 B に任せると宣言しているか
- 節の id が他のブロックの輪の中の節・ラインの include の id とぶつからないか（Ruling R17・R19）
- つなぎのスクリプト: intake（依頼と前提の実測を確かめ、作業ツリーの写しを盤面に置く。拒めば終了コード 1）・
  accept（check_purpose を script_io で包む）・collect（盤面の purpose.json から出口を組む）を別のプロセスで回す
- 受け付けの中身（.shared/core/purpose.py）: 写しの graph の post_check を graph から引いて当てるか
- 筋書き（fixtures/）が 3 本在り、期待の形がこの検査どおりか。Archon で回すのは dev/check.sh（workflow test）
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-purpose"
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))

import purpose  # noqa: E402
from accept import role_schema  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from engine.util import Reject  # noqa: E402

DEADLINE = 1728000000
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
PLANNED_INCLUDE_ID = "purposing"   # 線 B の周の線がこのブロックを include する id（rounds-spec-draft 2.2）


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def workflow(folder="blk-purpose"):
    return yaml.safe_load((ROOT / folder / f"{folder}.yaml").read_text(encoding="utf-8"))


def find_node(y, nid):
    """節を id で引く。loop_group の中の節も辿る"""
    def walk(nodes):
        for n in nodes or []:
            if n.get("id") == nid:
                return n
            if "loop_group" in n:
                hit = walk(n["loop_group"].get("nodes"))
                if hit is not None:
                    return hit
        return None
    n = walk(y.get("nodes"))
    if n is None:
        raise AssertionError(f"節 {nid} が無い")
    return n


def body_ids(nodes):
    """輪の中の節の id（入れ子も辿る）"""
    out = []
    for n in nodes:
        if "loop_group" in n:
            inner = n["loop_group"]["nodes"]
            out += [m["id"] for m in inner] + body_ids(inner)
    return out


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()

    def test_purpose_output_format_matches_role_schema(self):
        import node_marker
        fmt = find_node(self.y, "purpose")["output_format"]
        self.assertEqual(fmt, node_marker.mark(role_schema("p0.purpose"), "purpose"))   # 印（works-node: purpose）つき
        self.assertEqual(node_marker.strip(fmt), role_schema("p0.purpose"))

    def test_samples_against_output_format(self):
        fmt = find_node(self.y, "purpose")["output_format"]
        self.assertEqual(validate_schema(load("purpose_ok"), fmt), [])
        self.assertNotEqual(validate_schema(load("purpose_bad_source"), fmt), [])

    def test_signature(self):
        self.assertEqual(self.y["name"], "blk-purpose")
        self.assertEqual(set(self.y["inputs"]), {"request", "constraints_file", "base_rev"})
        self.assertIs(self.y["inputs"]["request"].get("required"), True)
        self.assertEqual(self.y["inputs"]["constraints_file"].get("default"), "")   # 前提の実測は任意
        self.assertEqual(self.y["inputs"]["base_rev"].get("default"), "")          # Ruling R2
        self.assertEqual(self.y["returns"], "collect")
        self.assertEqual(self.y["outcome_field"], "ok")
        fmt = find_node(self.y, "collect")["output_format"]
        self.assertEqual(fmt["properties"], {
            "ok": {"type": "boolean"}, "purpose_file": {"type": "string"},
            "purpose_text": {"type": "string"}, "source": {"type": "string"}})
        self.assertEqual(sorted(fmt["required"]), ["ok", "purpose_file", "purpose_text", "source"])

    def test_nodes_and_loop(self):
        self.assertEqual([n["id"] for n in self.y["nodes"]], ["intake", "purpose-loop", "collect"])
        intake = find_node(self.y, "intake")
        self.assertEqual((intake["script"], intake["runtime"], intake["timeout"]), ("intake", "uv", DEADLINE))
        self.assertEqual(intake["with"], {"request": "$INPUTS.request", "constraints_file": "$INPUTS.constraints_file"})
        g = find_node(self.y, "purpose-loop")
        self.assertEqual(g["depends_on"], ["intake"])
        lg = g["loop_group"]
        self.assertEqual((lg["max_iterations"], lg["fresh_context"], lg["until_bash"]),
                         (3, False, "test $purpose-accept.output.ok = true"))
        self.assertEqual([n["id"] for n in lg["nodes"]], ["purpose", "purpose-accept"])
        role = find_node(self.y, "purpose")
        self.assertEqual(role["command"], "purpose")
        self.assertEqual(role["settingSources"], ["user"])
        self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob"])
        self.assertEqual(role["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(role["idle_timeout"], DEADLINE)
        self.assertNotIn("model", role)
        acc = find_node(self.y, "purpose-accept")
        self.assertEqual((acc["script"], acc["runtime"], acc["timeout"], acc["depends_on"]),
                         ("accept", "uv", DEADLINE, ["purpose"]))
        self.assertEqual(acc["with"], {"reply": {"from": "$purpose.output"}, "base_rev": "$INPUTS.base_rev"})
        self.assertEqual(acc["output_format"]["properties"], {
            "ok": {"type": "boolean"}, "reason": {"type": "string"}, "reason_file": {"type": "string"},
            "purpose_file": {"type": "string"}})
        self.assertEqual(sorted(acc["output_format"]["required"]), ["ok", "purpose_file", "reason", "reason_file"])
        col = find_node(self.y, "collect")
        self.assertEqual((col["script"], col["runtime"], col["timeout"], col["depends_on"]),
                         ("collect", "uv", DEADLINE, ["purpose-loop"]))

    def test_purpose_review_is_declared_for_track_b(self):
        # p0.purpose_review（出典が ③ の周に立つ別の目）はこのブロックに入れない。その宣言と理由を YAML に残す
        text = (BLK / "blk-purpose.yaml").read_text(encoding="utf-8")
        self.assertIn("p0.purpose_review", text)
        self.assertIn("purpose_review_due", text)
        self.assertIn("線 B", text)
        # 指示書も審査の今の状態（works に無い・線 B が持つ）を役に告げる。線 B が入った時に直し忘れればここで落ちる
        prompt = (BLK / "commands" / "purpose.md").read_text(encoding="utf-8")
        self.assertIn("works では今この審査はまだ無い", prompt)
        self.assertIn("p0.purpose_review` は線 B", prompt)
        ai = [n["id"] for n in self.y["nodes"] + [m for g in self.y["nodes"] if "loop_group" in g
                                                   for m in g["loop_group"]["nodes"]]
              if "command" in n or "prompt" in n]
        self.assertEqual(ai, ["purpose"])

    def test_ids_do_not_collide(self):
        # Ruling R17: include の id とブロックの中の節の id を重ねない。Ruling R19: 輪の中の節は模擬実行で名前空間の
        # 付かない id で stub を引くので、ブロックをまたいで重ねない
        mine = self.y["nodes"]
        ids = {n["id"] for n in mine} | set(body_ids(mine))
        self.assertNotIn(PLANNED_INCLUDE_ID, ids)
        line = yaml.safe_load((ROOT / "darkfactory" / "darkfactory.yaml").read_text(encoding="utf-8"))
        self.assertEqual({n["id"] for n in line["nodes"] if "include" in n} & ids, set())
        for p in sorted(ROOT.glob("blk-*/blk-*.yaml")):
            if p.parent.name == "blk-purpose" or p.stem != p.parent.name:
                continue
            with self.subTest(p.parent.name):
                self.assertEqual(set(body_ids(yaml.safe_load(p.read_text(encoding="utf-8"))["nodes"]))
                                 & set(body_ids(mine)), set())

    def test_prompt_wires_inputs_and_retry_reason(self):
        text = (BLK / "commands" / "purpose.md").read_text(encoding="utf-8")
        # 理由の本文は貼らない（Archon は $LOOP_PREV で貼った中身をもう一度置き換えに通す。裁定 R44）。パスだけを貼って Read させる
        self.assertEqual(re.findall(r"\$LOOP_PREV\.[\w.-]*", text), ["$LOOP_PREV.purpose-accept.output.reason_file"])
        for needle in ("$INPUTS.request", "$INPUTS.constraints_file", "$LOOP_PREV.purpose-accept.output.reason_file",
                       "①PR 説明", "②計画・タスク記述", "③writer の要約", "目的不明",
                       "source_files", "known_weaknesses", "判定役", "2 周空転", "実測 2026-09-13", "仮説"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertNotIn("{{", text, "engine の穴が残っている")

    def test_fixtures(self):
        want = {
            "pass": {"expect": "completed", "inputs": {"request": "request_ok.json"},
                     "reached": ["intake", "purpose", "purpose-accept", "collect"]},
            "bad-reply": {"expect": "failed", "fail-node": "collect",
                          "reached": ["intake", "purpose", "purpose-accept"]},
            "bad-request": {"expect": "failed", "fail-node": "intake", "inputs": {"request": "missing.json"}},
        }
        self.assertEqual({p.name.split(".")[0] for p in (BLK / "fixtures").glob("*.stubs.yaml")}, set(want))
        for name, decl in want.items():
            with self.subTest(name):
                f = yaml.safe_load((BLK / "fixtures" / f"{name}.stubs.yaml").read_text(encoding="utf-8"))
                self.assertIs(f["exec-code"], True)
                for k, v in decl.items():
                    self.assertEqual(f["fixture"][k], v)
        stub = lambda n: yaml.safe_load((BLK / "fixtures" / f"{n}.stubs.yaml").read_text(encoding="utf-8"))["purpose"]
        self.assertEqual(stub("pass"), load("purpose_ok"))
        self.assertEqual(stub("bad-reply"), load("purpose_missing_source_file"))
        # 模擬実行は stub を役の output_format に通すので、受け付けまで届く悪い返答は型には合う物
        self.assertEqual(validate_schema(stub("bad-reply"), find_node(self.y, "purpose")["output_format"]), [])

    def test_seed_has_source_file(self):
        # 筋書きの目的の出典（source_files）は種に在る（受け付けが作業ツリーで引く）
        for f in load("purpose_ok")["source_files"]:
            self.assertTrue((SEED / f).is_file(), f)


class ScriptCase(unittest.TestCase):
    """スクリプトを別のプロセスで回す。cwd は種を写した使い捨ての git リポジトリ"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        shutil.copytree(SEED, self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed")
        self.art = self.tmp / "art"
        self.board = self.art / "board"

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, name, cwd=None, **env):
        # 外の INPUTS_*（Archon の run の中で回すと、ラインの入口が環境に居る）を持ち込まない。欠けの検査が狂う
        base = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        e = dict(base, ARTIFACTS_DIR=str(self.art), **env)
        return subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=cwd or self.repo, env=e,
                              capture_output=True, text=True, timeout=300)

    def intake(self, request="request_ok.json", constraints="", cwd=None):
        return self.run_script("intake", cwd=cwd, INPUTS_REQUEST=request, INPUTS_CONSTRAINTS_FILE=constraints)

    def accept(self, reply, cwd=None):
        r = self.run_script("accept", cwd=cwd, INPUTS_REPLY=json.dumps(reply, ensure_ascii=False), INPUTS_BASE_REV="")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def outside(self, sample):
        p = self.tmp / "outside" / f"{sample}.json"
        p.parent.mkdir(exist_ok=True)
        shutil.copy(REPLIES / f"{sample}.json", p)
        return p

    # ---- intake
    def test_intake_without_constraints(self):
        r = self.intake()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout),
                         {"ok": True, "reason": "", "request": "request_ok.json", "constraints_file": ""})
        self.assertEqual(json.loads((self.board / purpose.SNAPSHOT_FILE).read_text(encoding="utf-8")),
                         purpose.tree_state(self.repo))   # 共通の作業ツリーの姿（HEAD・枝つき。裁定 R47）
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")   # 対象の作業ツリーは汚さない

    def test_intake_with_constraints_outside_repo(self):
        # 前提の実測は blk-premises が盤面（対象の外）に置く p0.premises の返答。絶対パスで渡る
        p = self.outside("purpose_constraints_ok")
        r = self.intake(constraints=str(p))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["constraints_file"], str(p))

    def test_intake_rejects_constraints(self):
        (self.tmp / "outside").mkdir()
        broken = self.tmp / "outside" / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        extra = self.tmp / "outside" / "extra.json"
        extra.write_text(json.dumps({"constraints": [], "note": "x"}), encoding="utf-8")
        for label, path, needle in (
                ("missing", str(self.tmp / "outside" / "nope.json"), "nope.json"),
                ("not-json", str(broken), "JSON"),
                ("schema", str(extra), "note"),
                # 写しの p0.premises の post_check（measured_needs_output）: kind=実測 は出力が要る
                ("post-check", str(self.outside("purpose_constraints_no_output")), "measured_output")):
            with self.subTest(label):
                r = self.intake(constraints=path)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(needle, r.stderr)
                self.assertEqual(r.stderr.strip().count("\n"), 0, "理由は 1 行")
                self.assertFalse((self.board / purpose.SNAPSHOT_FILE).exists())

    def test_intake_missing_request(self):
        r = self.intake(request="missing.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing.json", r.stderr)
        self.assertEqual(r.stderr.strip().count("\n"), 0, "理由は 1 行")

    def test_intake_missing_env(self):
        r = self.run_script("intake", INPUTS_REQUEST="request_ok.json")
        self.assertEqual(r.returncode, 2)
        self.assertIn("INPUTS_CONSTRAINTS_FILE", r.stderr)
        r = self.run_script("intake", INPUTS_CONSTRAINTS_FILE="")
        self.assertEqual(r.returncode, 2)
        self.assertIn("INPUTS_REQUEST", r.stderr)

    def test_intake_refuses_when_purpose_is_frozen(self):
        # graph の once: 目的の文は 1 度だけ固める。盤面に在れば役を起こさない
        self.board.mkdir(parents=True)
        (self.board / purpose.PURPOSE_FILE).write_text(json.dumps(load("purpose_ok")), encoding="utf-8")
        r = self.intake()
        self.assertEqual(r.returncode, 1)
        self.assertIn(purpose.PURPOSE_FILE, r.stderr)

    # ---- accept
    def test_accept_good_and_bad_reply(self):
        self.assertEqual(self.intake().returncode, 0)
        got = self.accept(load("purpose_bad_source"))
        self.assertIs(got["ok"], False)
        self.assertIn("source", got["reason"])
        self.assertEqual(got["purpose_file"], "")
        self.assertFalse((self.board / purpose.PURPOSE_FILE).exists())
        got = self.accept(load("purpose_ok"))
        # 盤面のパスは script_io.main が一度だけ resolve した値（7d22ce7。macOS の一時の置き場は /private/var の symlink）
        self.assertEqual(got, {"ok": True, "reason": "", "reason_file": "",
                               "purpose_file": str(self.board.resolve() / purpose.PURPOSE_FILE)})
        self.assertEqual(json.loads((self.board / purpose.PURPOSE_FILE).read_text(encoding="utf-8")), load("purpose_ok"))

    def test_accept_unknown_purpose(self):
        # 出典が 1 つも得られない目的不明も、型に通れば受け付ける（R2 が unverifiable になるのは周の線の仕事）
        self.assertEqual(self.intake().returncode, 0)
        reply = {"purpose_text": "目的の出典が得られない", "source": "目的不明", "known_weaknesses": [], "source_files": []}
        self.assertIs(self.accept(reply)["ok"], True)

    def test_accept_rejects_missing_source_file_sample(self):
        # 筋書き bad-reply の返答は型に通り、受け付けの source_files の検査で拒まれる
        self.assertEqual(self.intake().returncode, 0)
        got = self.accept(load("purpose_missing_source_file"))
        self.assertIs(got["ok"], False)
        self.assertIn("docs/plan.md", got["reason"])

    def test_accept_rejects_tree_change_after_intake(self):
        self.assertEqual(self.intake().returncode, 0)
        (self.repo / "extra.txt").write_text("読むだけの役が書いた\n", encoding="utf-8")
        got = self.accept(load("purpose_ok"))
        self.assertIs(got["ok"], False)
        self.assertIn("extra.txt", got["reason"])
        self.assertFalse((self.board / purpose.PURPOSE_FILE).exists())

    def test_accept_names_branch_and_ignored_changes(self):
        # 比べは共通の tree_state・tree_moved（裁定 R47）: 中身の同じ枝の切り替え（ref だけ変わる）も拒み、拒否の文は変わった欄
        # （ref・git が無視するパスの増えた物）を名指す
        self.assertEqual(self.intake().returncode, 0)
        git(self.repo, "switch", "-q", "-c", "役が切った枝")
        got = self.accept(load("purpose_ok"))
        self.assertIs(got["ok"], False)
        self.assertIn("refs/heads/役が切った枝", got["reason"])
        git(self.repo, "switch", "-q", "-")
        with open(self.repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as f:
            f.write("\n*.役の残り\n")
        (self.repo / "x.役の残り").write_text("役が書いた\n", encoding="utf-8")
        got = self.accept(load("purpose_ok"))
        self.assertIs(got["ok"], False)
        self.assertIn("git が無視するパス: 増えた ['x.役の残り'] 消えた []", got["reason"])
        (self.repo / "x.役の残り").unlink()
        self.assertIs(self.accept(load("purpose_ok"))["ok"], True)

    def test_accept_rejects_source_files_outside_tree(self):
        # source_files はリポジトリ相対の実在するファイル。外や無い名前だと、前の周の修正が触ったファイルとの
        # 突き合わせ（写しの purpose_sources_changed）が黙って当たらなくなる
        self.assertEqual(self.intake().returncode, 0)
        for bad in (str(self.repo / "stats.py"), "../repo/stats.py", "nope.md", "", "."):
            with self.subTest(bad):
                got = self.accept(dict(load("purpose_ok"), source_files=["stats.py", bad]))
                self.assertIs(got["ok"], False)
                self.assertIn("source_files", got["reason"])
                self.assertIn(repr(bad), got["reason"])
                self.assertNotIn("'stats.py'", got["reason"].replace(repr(bad), ""))
        self.assertFalse((self.board / purpose.PURPOSE_FILE).exists())

    def test_accept_rejects_source_files_not_in_git_form(self):
        # 在るファイルを指していても、git の出す形（`git diff --name-only` の名前）でなければ突き合わせで完全一致に
        # 当たらず、once で凍る。正規化して通さず、拒んで出し直させる
        self.assertEqual(self.intake().returncode, 0)
        for bad in ("./stats.py", "stats.py/", ".//stats.py", "././/stats.py", "STATS.py", "Stats.py"):
            with self.subTest(bad):
                got = self.accept(dict(load("purpose_ok"), source_files=["stats.py", bad]))
                self.assertIs(got["ok"], False)
                self.assertIn("source_files", got["reason"])
                self.assertIn(repr(bad), got["reason"])
        self.assertFalse((self.board / purpose.PURPOSE_FILE).exists())

    def test_source_files_errors_nested_and_ignored(self):
        # a//b・a/./b は綴り（_resolve_target）で、git が無視するファイルは版の一覧（_in_version）で落ちる。未追跡の新規は
        # _files_changed_since が拾うので通す
        (self.repo / "sub").mkdir()
        (self.repo / "sub" / "a.md").write_text("x\n", encoding="utf-8")
        (self.repo / "sub" / "new.md").write_text("x\n", encoding="utf-8")
        (self.repo / "sub" / "skip.log").write_text("x\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
        git(self.repo, "add", "sub/a.md", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "sub")
        files = ["sub/a.md", "sub//a.md", "sub/./a.md", "sub/new.md", "sub/skip.log"]
        self.assertEqual(purpose._source_files_errors(files, self.repo), ["sub//a.md", "sub/./a.md", "sub/skip.log"])

    def round_trip(self, cwd, names):
        # 往復: 受け付けを通った source_files を直すと、写しの purpose_sources_changed が突き合わせる
        # _files_changed_since（前の周の頭の版と今の作業ツリーの木の差）の名前と字のまま同じになる。
        # 相手は本物の _files_changed_since——試験の中で git diff を組み直すと、自分の写しを測る
        self.assertEqual(self.intake(cwd=cwd).returncode, 0)
        self.assertIs(self.accept(dict(load("purpose_ok"), source_files=names), cwd=cwd)["ok"], True)
        srcs = json.loads((self.board / purpose.PURPOSE_FILE).read_text(encoding="utf-8"))["source_files"]
        self.assertEqual(srcs, names)
        rules = purpose._rules()
        with purpose._in_repo(cwd):
            head = rules._worktree_tree()   # 前の周の頭（intake の時の作業ツリー）
        top = pathlib.Path(git(cwd, "rev-parse", "--show-toplevel").strip())
        for f in srcs:
            with (top / f).open("a", encoding="utf-8") as fh:
                fh.write("直した\n")
        b = purpose.DiskBoard.scratch(self.board, review_rev="", loop_state={"head_revs": {"1": head}})
        with purpose._in_repo(cwd):
            changed = rules._files_changed_since(b, 1)
        self.assertEqual(changed, sorted(srcs))

    def test_accepted_source_files_match_files_changed_since(self):
        # 追跡中・未追跡の新規・空白を含む名前・非 ASCII の名前
        (self.repo / "docs").mkdir()
        for f in ("docs/空白 と 日本語.md", "new notes.md"):
            (self.repo / f).write_text("x\n", encoding="utf-8")
        self.round_trip(self.repo, ["stats.py", "docs/空白 と 日本語.md", "new notes.md"])

    def test_accepted_source_files_match_files_changed_since_from_subdir(self):
        # repo が作業ツリーの根でない（サブディレクトリで回す）: 受け付けは根からの相対の名前を通し、cwd からの相対の
        # 名前は拒む。通した名前は _files_changed_since の名前（根からの相対）と字のまま同じ
        outer = self.tmp / "outer"
        sub = outer / "pkg"
        shutil.copytree(SEED, sub)
        git(outer, "init", "-q")
        git(outer, "add", "-A")
        git(outer, "commit", "-q", "-m", "seed")
        (sub / "新規 メモ.md").write_text("x\n", encoding="utf-8")
        self.assertEqual(purpose._source_files_errors(["stats.py", "pkg/stats.py", "pkg/新規 メモ.md", "新規 メモ.md"], sub),
                         ["stats.py", "新規 メモ.md"])
        self.round_trip(sub, ["pkg/stats.py", "pkg/新規 メモ.md"])

    def test_accept_refuses_to_overwrite_frozen_purpose(self):
        self.assertEqual(self.intake().returncode, 0)
        self.assertIs(self.accept(load("purpose_ok"))["ok"], True)
        before = (self.board / purpose.PURPOSE_FILE).read_bytes()
        got = self.accept(dict(load("purpose_ok"), purpose_text="後から広げた目的"))
        self.assertIs(got["ok"], False)
        self.assertIn("once", got["reason"])
        self.assertEqual((self.board / purpose.PURPOSE_FILE).read_bytes(), before)

    def test_check_purpose_without_snapshot_needs_clean_tree(self):
        self.board.mkdir(parents=True)
        (self.repo / "extra.txt").write_text("x\n", encoding="utf-8")
        r = purpose.check_purpose(load("purpose_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("extra.txt", r["reason"])

    def test_check_purpose_without_snapshot_rejects_ignored_file(self):
        # 写しが無い時も、git が無視するファイルを読むだけの役が作れば拒む（判定役の確かめと同じ。accept._judge_tree_unchanged）
        self.board.mkdir(parents=True)
        with open(self.repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as f:
            f.write("\n*.leftover\n")
        (self.repo / "x.leftover").write_text("x\n", encoding="utf-8")
        r = purpose.check_purpose(load("purpose_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("!! x.leftover", r["reason"])

    def test_check_purpose_runs_graph_post_check(self):
        # 写しの graph の p0.purpose に post_check が在れば当てる（今の写しは持たない。写し直しで足されても黙って落とさない）
        self.board.mkdir(parents=True)
        called = []

        def fake(b, nid, out, item):
            called.append(nid)
            raise Reject(f"{nid}: 偽の post_check が拒んだ")
        g = json.loads(json.dumps(purpose._graph()))
        g["nodes"]["p0.purpose"]["post_check"] = "fake_check"
        rules = purpose._rules()
        with mock.patch.object(purpose, "_graph", return_value=g), \
                mock.patch.dict(rules.POST_CHECKS, {"fake_check": fake}):
            r = purpose.check_purpose(load("purpose_ok"), self.board, "", self.repo)
        self.assertEqual(called, ["p0.purpose"])
        self.assertIs(r["ok"], False)
        self.assertIn("偽の post_check", r["reason"])

    def test_accept_missing_env(self):
        r = self.run_script("accept", INPUTS_REPLY="{}")
        self.assertEqual(r.returncode, 2)

    # ---- collect
    def test_collect_builds_exit(self):
        self.assertEqual(self.intake().returncode, 0)
        self.assertIs(self.accept(load("purpose_ok"))["ok"], True)
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got, {"ok": True, "purpose_file": str(self.board / purpose.PURPOSE_FILE),
                               "purpose_text": load("purpose_ok")["purpose_text"],
                               "source": load("purpose_ok")["source"]})
        self.assertEqual(validate_schema(got, find_node(workflow(), "collect")["output_format"]), [])

    def test_collect_without_purpose(self):
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 1)
        self.assertIn(purpose.PURPOSE_FILE, r.stderr)

    def test_collect_broken_purpose(self):
        self.board.mkdir(parents=True)
        (self.board / purpose.PURPOSE_FILE).write_text(json.dumps({"purpose_text": "x"}), encoding="utf-8")
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 1)
        self.assertIn("source", r.stderr)

    def test_collect_missing_env(self):
        e = {k: v for k, v in os.environ.items() if k != "ARTIFACTS_DIR" and not k.startswith("INPUTS_")}
        r = subprocess.run([sys.executable, str(BLK / "scripts" / "collect.py")], cwd=self.repo, env=e,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 2)
        self.assertIn("ARTIFACTS_DIR", r.stderr)


if __name__ == "__main__":
    unittest.main()
