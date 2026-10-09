"""固定材料（.shared/core/fixture.py。計画 220 Task 5）の検査。

語:
- 固定材料: h-fix の時の盤面の写し（$ARTIFACTS_DIR/fix-fixture/board/）と、その横の控え fixture.json（木の hash・依頼の sha256・
  test_cmd・ファイルごとの sha256）。次の run が入力 fix_fixture で写しを取り込み、判定と修正案を作り直さずに修正から始める。
- 取り込み（adopt）: 同じ木・同じ依頼・同じ test_cmd・書き換えていない写しの時だけ、写しを新しい盤面の置き場へ写し、根のパスと
  HEAD を新しい値に置き換える。違えば盤面を作らずに何が違うかを名指して拒む。

盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で p3.fix が待つ所まで進める。
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import test_blk_fix as tbf  # noqa: E402
import entry  # noqa: E402
import fixture  # noqa: E402
import startrec  # noqa: E402  （始めの記録の置き場と読み口）
import line_edge  # noqa: E402
import linekit  # noqa: E402
import stopby  # noqa: E402  （止めの理由の住処）

PACK = entry.PACK
REQUEST_TEXT = (ROOT / "dev" / "target-seed" / "request_ok.json").read_text(encoding="utf-8")


def trace_ops(board, op):
    p = pathlib.Path(board) / "trace.jsonl"
    return [r for r in (json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()) if r.get("op") == op]


class FixtureBase(tbf.BoardCase):
    """固定材料の試験の手助け（試験を持たない）"""

    def clone_same_tree(self):
        """同じ木で別の置き場・別の commit（種を写し直し、空の commit を 1 本足す）"""
        other = linekit.seed_repo(self.tmp / "other", declared=True)
        linekit.git(other, "commit", "-q", "--allow-empty", "-m", "other")
        return other

    def captured(self):
        self.fix_ready()
        man = fixture.capture(self.board, self.repo, run_id="run-1", pack_root=PACK)
        return man, self.board.parent / fixture.DIR

    def inputs(self, repo, **raw):
        """今の run の入力（線の start と同じ手順: check_inputs の返りから start の控えに残す欄）"""
        given = {"request": str(self.tmp / "request.json"), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "",
                 "adapter": "", "policy_md": "", **raw}
        return entry.adopt_inputs(entry.check_inputs(given, repo))

    def adopt(self, src, repo, new_board=None, raw=None, **kw):
        args = {"run_id": "run-2", "pack_root": PACK, "request_text": REQUEST_TEXT, "inputs": self.inputs(repo, **(raw or {})),
                **kw}
        return fixture.adopt(new_board or self.tmp / "b2" / "board", src, repo, **args)

    def refused(self, src, repo, *words, new_board=None, raw=None, **kw):
        new_board = new_board or self.tmp / "b2" / "board"
        with self.assertRaises(fixture.FixtureRefused) as cm:
            self.adopt(src, repo, new_board, raw=raw, **kw)
        for w in words:
            self.assertIn(w, str(cm.exception))
        self.assertEqual(len(str(cm.exception).splitlines()), 1, "理由は 1 行")
        return new_board


class FixtureCase(FixtureBase):
    def test_capture_then_adopt_elsewhere_rewrites_roots(self):
        """写した盤面を別の置き場・別の commit（同じ木）で取り込む → 控えの run_id・出どころが今の値、古い盤面・対象の根・
        HEAD の字がどのファイルにも残らず、p3.fix が待つ"""
        man, src = self.captured()
        other_repo = self.clone_same_tree()
        new_board = self.tmp / "b2" / "board"
        doc = self.adopt(src, other_repo, new_board)
        self.assertEqual((doc["run_id"], doc["fixture"]["source_run"]), ("run-2", "run-1"))
        self.assertNotIn("fix_shape", doc)
        self.assertEqual(doc["fixture"]["manifest_sha256"],
                         hashlib.sha256((src / fixture.MANIFEST).read_bytes()).hexdigest())
        self.assertEqual(json.loads((new_board / startrec.REL).read_text(encoding="utf-8")), doc)
        texts = [p.read_text(encoding="utf-8", errors="ignore") for p in new_board.rglob("*") if p.is_file()]
        for old in (str(self.board), str(self.board.parent), str(self.repo), man["head"]):
            self.assertFalse(any(old in t for t in texts), old)
        self.assertIn("p3.fix", entry.open_board(new_board).ready())
        # 写しの engine が作業ツリーを固めた版（review_rev）は元の対象にしか無いので、同じ木で作り直して名を置き換える
        old_rev = json.loads((src / "board" / "state.json").read_text(encoding="utf-8"))["inputs"]["review_rev"]
        self.assertIn(old_rev, man["commits"])
        rev = json.loads((new_board / "state.json").read_text(encoding="utf-8"))["inputs"]["review_rev"]
        self.assertNotEqual(rev, old_rev)
        self.assertEqual(linekit.git(other_repo, "rev-parse", f"{rev}^{{tree}}"), man["commits"][old_rev])
        self.assertFalse(any(old_rev in t for t in texts), old_rev)
        # 固定材料の印の読み口は 1 つ（取り込んだ時刻を持つ）。元の盤面は固定材料の盤面でない
        self.assertEqual(fixture.adopted(new_board), doc["fixture"])
        self.assertTrue(doc["fixture"]["at"])
        self.assertIsNone(fixture.adopted(self.board))
        self.assertEqual(doc["request_file"], str(self.tmp / "request.json"), "依頼のファイルは今の入力の値")

    def test_adopt_carries_outside_files(self):
        """盤面の字が指す $ARTIFACTS_DIR の下・盤面の外のファイル → 写しの outside に運び、取り込んだ盤面の中へ写して名を替える。
        元の置き場が消えても取り込んだ盤面は読める"""
        self.fix_ready()
        design = self.board.parent / "structure" / "design.jsonl"
        design.parent.mkdir(parents=True)
        design.write_text('{"row": 1}\n', encoding="utf-8")
        (self.board / "structure-ref.json").write_text(json.dumps({"design_file": str(design)}), encoding="utf-8")
        man = fixture.capture(self.board, self.repo, run_id="run-1", pack_root=PACK)
        self.assertIn(f"{fixture.OUTSIDE}/structure/design.jsonl", man["files"])
        self.assertNotIn(f"{fixture.OUTSIDE}/{fixture.DIR}", "\n".join(man["files"]))
        src = self.board.parent / fixture.DIR
        import shutil
        shutil.rmtree(design.parent)
        new_board = self.tmp / "b2" / "board"
        self.adopt(src, self.clone_same_tree(), new_board)
        moved = pathlib.Path(json.loads((new_board / "structure-ref.json").read_text(encoding="utf-8"))["design_file"])
        self.assertTrue(moved.is_relative_to(new_board), moved)
        self.assertEqual(moved.read_text(encoding="utf-8"), '{"row": 1}\n')

    def test_capture_carries_only_named_outside_files(self):
        """盤面の字が指さない $ARTIFACTS_DIR の下のファイル（run ごとの置き場 run-place の uv の cache・名指されない物）は運ばない。
        名指された物は run-place の下でも運ぶ"""
        self.fix_ready()
        art = self.board.parent
        cache = art / "run-place" / "uv-cache" / "wheels" / "big.whl"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"\0" * 4096)
        named = art / "run-place" / "g1-patch-1.diff"
        named.write_text("diff\n", encoding="utf-8")
        stray = art / "notes" / "stray.txt"
        stray.parent.mkdir(parents=True)
        stray.write_text("盤面は指さない\n", encoding="utf-8")
        (self.board / "ref.json").write_text(json.dumps({"patch": str(named)}), encoding="utf-8")
        man = fixture.capture(self.board, self.repo, run_id="run-1", pack_root=PACK)
        outside = sorted(p for p in man["files"] if p.startswith(f"{fixture.OUTSIDE}/"))
        self.assertEqual(outside, [f"{fixture.OUTSIDE}/run-place/g1-patch-1.diff"])
        self.assertFalse((art / fixture.DIR / fixture.OUTSIDE / "run-place" / "uv-cache").exists())

    def test_adopt_rewrites_pack_root(self):
        """別の works の置き場（pack_root）で取り込む → 盤面の中の works の置き場の字が新しい値になる"""
        _, src = self.captured()
        new_board = self.tmp / "b2" / "board"
        other_pack = self.tmp / "other-pack" / "works"
        self.adopt(src, self.clone_same_tree(), new_board, pack_root=other_pack)
        state = (new_board / "state.json").read_text(encoding="utf-8")
        self.assertNotIn(str(PACK), state)
        self.assertIn(str(other_pack), state)

    def test_adopt_refuses_commit_without_tree(self):
        """盤面の字が指す commit が対象に無く、その木も無い → 作り直せないので拒む（盤面は作らない）"""
        self.fix_ready()
        linekit.git(self.repo, "checkout", "-q", "-b", "side")
        (self.repo / "side.txt").write_text("side\n", encoding="utf-8")
        linekit.git(self.repo, "add", "-A")
        linekit.git(self.repo, "commit", "-q", "-m", "side")
        side = linekit.git(self.repo, "rev-parse", "HEAD")
        linekit.git(self.repo, "checkout", "-q", "-")
        (self.board / "side-ref.json").write_text(json.dumps({"rev": side}), encoding="utf-8")
        man = fixture.capture(self.board, self.repo, run_id="run-1", pack_root=PACK)
        self.assertIn(side, man["commits"])
        new_board = self.refused(self.board.parent / fixture.DIR, self.clone_same_tree(), side[:12])
        self.assertFalse(new_board.exists())

    def test_manifest_shape(self):
        """控えの欄: 出どころの run・HEAD・木・3 つの根・依頼の sha256・test_cmd・写しのファイルごとの sha256。時刻を書かない"""
        man, src = self.captured()
        self.assertEqual(set(man), {"source_run", "head", "tree", "board_root", "repo_root", "pack_root", "request_sha256",
                                    "test_cmd", "commits", "files"})
        self.assertEqual(json.loads((src / fixture.MANIFEST).read_text(encoding="utf-8")), man)
        self.assertEqual((man["source_run"], man["head"], man["tree"]),
                         ("run-1", linekit.git(self.repo, "rev-parse", "HEAD"), linekit.git(self.repo, "rev-parse", "HEAD^{tree}")))
        self.assertEqual((man["board_root"], man["repo_root"], man["pack_root"]),
                         (str(self.board.resolve()), str(self.repo.resolve()), str(PACK)))
        self.assertEqual(man["request_sha256"], hashlib.sha256(REQUEST_TEXT.encode("utf-8")).hexdigest())
        self.assertEqual(man["test_cmd"], "")
        copied = {p.relative_to(src).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in src.rglob("*") if p.is_file() and p.name != fixture.MANIFEST}
        self.assertEqual(man["files"], copied)
        self.assertIn(f"{fixture.COPY}/state.json", man["files"])

    def test_start_record_place_is_one(self):
        """start の控えの置き場は包みの START_REL 1 つ（1 周目の startrec.NAME）。固定材料の印の読み口は adopted だけ"""
        import adapter
        self.assertEqual(startrec.REL, startrec.REL)
        self.assertEqual(startrec.REL, f"r1/{startrec.NAME}")
        self.assertIsNone(fixture.adopted(self.tmp / "nowhere"))

    def test_adopt_refuses_other_tree(self):
        """種の木にファイルを 1 つ足して commit → 拒む（tree）。盤面は作らない"""
        _, src = self.captured()
        other = self.clone_same_tree()
        (other / "extra.txt").write_text("x\n", encoding="utf-8")
        linekit.git(other, "add", "-A")
        linekit.git(other, "commit", "-q", "-m", "extra")
        new_board = self.refused(src, other, "tree")
        self.assertFalse(new_board.exists())

    def test_adopt_refuses_dirty_tree(self):
        """手元に変更（commit していない）→ 拒む。盤面は作らない"""
        _, src = self.captured()
        other = self.clone_same_tree()
        with open(other / "stats.py", "a", encoding="utf-8") as f:
            f.write("# 手元の変更\n")
        new_board = self.refused(src, other, "変更")
        self.assertFalse(new_board.exists())

    def test_adopt_refuses_edited_copy(self):
        """写しの state.json を書き換え・写しのファイルを消す・足す → 拒む（そのパスを名指す）"""
        _, src = self.captured()
        other = self.clone_same_tree()
        state = src / "board" / "state.json"
        raw = state.read_bytes()
        state.write_bytes(raw + b"\n")
        self.refused(src, other, "state.json")
        state.write_bytes(raw)
        extra = src / "board" / "r1" / "added.json"
        extra.write_text("{}\n", encoding="utf-8")
        self.refused(src, other, "r1/added.json")
        extra.unlink()
        gone = src / "board" / "record.json"
        kept = gone.read_bytes()
        gone.unlink()
        self.refused(src, other, "record.json")
        gone.write_bytes(kept)
        (src / fixture.MANIFEST).write_text("{", encoding="utf-8")
        self.refused(src, other, fixture.MANIFEST)
        (src / fixture.MANIFEST).unlink()
        self.refused(src, other, fixture.MANIFEST)

    def test_adopt_refuses_other_request_or_inputs(self):
        """依頼の文が違う・start の控えの入力の欄（test_cmd・final_gate など）が今の入力と違う → 拒む（何が違うかを名指す）。
        今の値にするのは run_id・request_file・fix_fixture・features_off・features_on だけ"""
        _, src = self.captured()
        other = self.clone_same_tree()
        self.refused(src, other, "依頼", request_text=REQUEST_TEXT + " ")
        self.refused(src, other, "test_cmd", raw={"test_cmd": "python3 -m unittest"})
        self.refused(src, other, "final_gate", raw={"final_gate": "when_needed"})
        self.refused(src, other, "adapter", raw={"adapter": "optional"})
        self.assertEqual(self.adopt(src, other, raw={"fix_fixture": str(src)})["fix_fixture"], str(src))

    def test_adopt_refuses_non_empty_board(self):
        """取り込む先の盤面の置き場が空でない → 拒む（中身を書かない）"""
        _, src = self.captured()
        new_board = self.tmp / "b2" / "board"
        new_board.mkdir(parents=True)
        (new_board / "keep.txt").write_text("x\n", encoding="utf-8")
        self.refused(src, self.clone_same_tree(), "空でない", new_board=new_board)
        self.assertEqual([p.name for p in new_board.iterdir()], ["keep.txt"])

    def test_capture_once(self):
        """2 度目の capture は控えも写しも書き直さない（最初の写しを返す）"""
        man, src = self.captured()
        before = (src / fixture.MANIFEST).read_bytes()
        (self.board / "trace.jsonl").write_text((self.board / "trace.jsonl").read_text(encoding="utf-8") + "{}\n",
                                                encoding="utf-8")
        again = fixture.capture(self.board, self.repo, run_id="run-other", pack_root=PACK)
        self.assertEqual(again, man)
        self.assertEqual((src / fixture.MANIFEST).read_bytes(), before)


class FixtureStartCase(FixtureBase):
    """線の start の分かれ（入力 fix_fixture）: 取り込み → 盤面を開く → trace → 切符。判定・修正案・CI を走らせ直さない"""

    def raw(self, src, **kw):
        return {"request": str(self.tmp / "request.json"), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "",
                "adapter": "", "policy_md": "", "fix_fixture": str(src), **kw}

    def test_start_from_fixture(self):
        """start が写しを取り込み、p3.fix が待つ盤面と今と同じ形の返りを出す（CI の役は起こさない）。trace に取り込みの行"""
        _, src = self.captured()
        other = self.clone_same_tree()
        new_board = self.tmp / "b2" / "board"
        out = entry.start(new_board, other, self.raw(src), run_id="run-2")
        first = json.loads((self.board / startrec.REL).read_text(encoding="utf-8"))
        self.assertTrue(out["ok"])
        self.assertEqual((out["ci_role_go"], out["pr_go"]), (False, first["pr_go"]))
        self.assertEqual(out["base_rev"], linekit.git(other, "rev-parse", "HEAD"))
        self.assertEqual(set(out), {"ok", "input", "pr_file", "base_rev", "test_cmd", "policy_paste", "policy_path",
                                    "adapter", "thickness", "gates", "ci_role_go", "pr_go", "head_line", *entry.FEATURES})
        adopted = startrec.read(new_board)
        self.assertEqual(out["input"], adopted["input"])   # 入口の入力の形は取り込んだ控えの物（固定材料の run は入口を測り直さない）
        self.assertEqual(set(out["input"]), set(first["input"]))
        self.assertEqual(out["input"]["requests"], first["input"]["requests"])
        self.assertEqual(out["pr_file"], "")
        self.assertIn("固定材料", out["head_line"])
        self.assertIn(startrec.words(adopted["input"]), out["head_line"])
        self.assertIn("p3.fix", entry.open_board(new_board).ready())
        self.assertEqual(len(trace_ops(new_board, fixture.TRACE_OP)), 1)

    def test_start_from_old_fixture_without_input_keeps_exit_contract(self):
        """入口の入力の形を持つ前の版の固定材料（控えに input が無い）から始めても、出口は入口のブロックの型を満たす（Archon は
        script の節の標準出力を output_format に当てて節を落とすので、input を null で出さず、欄ごと出さない）。頭の行はその事実を言う"""
        import yaml
        from engine.schema import validate_schema
        _, src = self.captured()
        other = self.clone_same_tree()
        real = fixture.adopt

        def old_adopt(board_dir, *a, **kw):
            doc = real(board_dir, *a, **kw)
            doc.pop("input", None)
            path = startrec.path(board_dir)
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            return doc
        with mock.patch.object(fixture, "adopt", side_effect=old_adopt):
            out = entry.start(self.tmp / "b-old" / "board", other, self.raw(src), run_id="run-old")
        self.assertNotIn("input", out)
        block = yaml.safe_load((ROOT / "blk-entry" / "blk-entry.yaml").read_text(encoding="utf-8"))
        fmt = next(n for n in block["nodes"] if n["id"] == block["returns"])["output_format"]
        self.assertEqual(validate_schema(out, fmt), [])
        self.assertIn("控えに入口の入力の形が無い", out["head_line"])

    def test_start_from_fixture_may_switch_features(self):
        """固定材料から始める run は切る機能・入れる機能（features_off・features_on）を写した run と替えてよい（今の値にする欄。修正の段の
        機能を切って同じ所から比べる）。出口と控えは今の値"""
        _, src = self.captured()
        other = self.clone_same_tree()
        new_board = self.tmp / "b3" / "board"
        out = entry.start(new_board, other, {**self.raw(src), "features_off": "fix_lanes", "features_on": "judge_verify"},
                          run_id="run-3")
        self.assertEqual((out["fix_lanes"], out["tdd_lanes"], out["judge_verify"]), ("off", "on", "on"))
        self.assertIn("機能: fix_lanes off・review_tree auto", out["head_line"])
        doc = json.loads((new_board / startrec.REL).read_text(encoding="utf-8"))
        self.assertEqual((doc["features_off"], doc["features_on"]), (["fix_lanes"], ["judge_verify"]))

    def test_start_resume_with_fixture_skips_adopt(self):
        """Archon の呼び直し: 前の start の控えに fixture が在れば取り込み直さずに盤面を開いて続ける（空でない置き場で拒まない）"""
        _, src = self.captured()
        other = self.clone_same_tree()
        new_board = self.tmp / "b2" / "board"
        entry.start(new_board, other, self.raw(src), run_id="run-2")
        again = entry.start(new_board, other, self.raw(src), run_id="run-2")
        self.assertTrue(again["ok"])
        self.assertEqual(len(trace_ops(new_board, fixture.TRACE_OP)), 1, "呼び直しは取り込み直さない")
        with self.assertRaises(entry.InputRefused):
            entry.start(new_board, other, self.raw(src, test_cmd="python3 -m unittest"), run_id="run-2")

    def test_start_refuses_bad_fixture_without_board(self):
        """違う依頼の写し → InputRefused（盤面を作らない）"""
        _, src = self.captured()
        other = self.clone_same_tree()
        other_req = self.tmp / "other-request.json"
        other_req.write_text(REQUEST_TEXT.replace("[", "[ ", 1), encoding="utf-8")
        new_board = self.tmp / "b2" / "board"
        with self.assertRaises(entry.InputRefused) as cm:
            entry.start(new_board, other, self.raw(src, request=str(other_req)), run_id="run-2")
        self.assertIn("依頼", str(cm.exception))
        self.assertFalse(new_board.exists())

    def test_start_refuses_other_works_version(self):
        """写しの graph_sha が今の works と違う（控えのファイルの sha256 は合わせた）→ 「固定材料と works の版が違う」で拒み、
        取り込んだ盤面を残さない"""
        _, src = self.captured()
        state = src / "board" / "state.json"
        doc = json.loads(state.read_text(encoding="utf-8"))
        doc["graph_sha"] = "0" * 64
        state.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        man = json.loads((src / fixture.MANIFEST).read_text(encoding="utf-8"))
        man["files"][f"{fixture.COPY}/state.json"] = hashlib.sha256(state.read_bytes()).hexdigest()
        (src / fixture.MANIFEST).write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        new_board = self.tmp / "b2" / "board"
        with self.assertRaises(entry.InputRefused) as cm:
            entry.start(new_board, self.clone_same_tree(), self.raw(src), run_id="run-2")
        self.assertIn("固定材料と works の版が違う", str(cm.exception))
        self.assertFalse(new_board.exists())

    def test_start_refuses_fixture_before_scope_layout(self):
        """この版より前に写した固定材料（盤面の state.works.layout が無い。部品の私物を include の scope の根に分けていない）→
        取り込んだ所で「固定材料と works の版が違う」で拒み、取り込んだ盤面を残さない（後の include の中の節で盤面が開けずに
        止まる run にしない。依頼 239）"""
        _, src = self.captured()
        state = src / "board" / "state.json"
        doc = json.loads(state.read_text(encoding="utf-8"))
        doc["works"].pop("layout")
        state.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        man = json.loads((src / fixture.MANIFEST).read_text(encoding="utf-8"))
        man["files"][f"{fixture.COPY}/state.json"] = hashlib.sha256(state.read_bytes()).hexdigest()
        (src / fixture.MANIFEST).write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        new_board = self.tmp / "b2" / "board"
        with self.assertRaises(entry.InputRefused) as cm:
            entry.start(new_board, self.clone_same_tree(), self.raw(src), run_id="run-2")
        self.assertIn("固定材料と works の版が違う", str(cm.exception))
        self.assertIn("layout", str(cm.exception))
        self.assertFalse(new_board.exists())

    def test_check_inputs_fix_fixture(self):
        """fix_fixture は空か在るフォルダ。相対なら対象の根から絶対にする。無いフォルダは InputRefused"""
        self.fix_ready()
        base = {"request": str(self.tmp / "request.json")}
        self.assertEqual(entry.check_inputs(base, self.repo)["fix_fixture"], "")
        (self.repo / "fx").mkdir()
        self.assertEqual(entry.check_inputs({**base, "fix_fixture": "fx"}, self.repo)["fix_fixture"], str(self.repo / "fx"))
        with self.assertRaises(entry.InputRefused) as cm:
            entry.check_inputs({**base, "fix_fixture": "nowhere"}, self.repo)
        self.assertIn("fix_fixture", str(cm.exception))


class FixtureEdgeCase(FixtureBase):
    """境の節 h-fix の写し（go の後の 1 段）と、固定材料から始めた盤面の h-judge・h-mat"""

    def edge(self, at, board=None, repo=None, adapter_mode="optional"):
        return line_edge.edge(board or self.board, at, repo or self.repo, run_id="run-1", adapter_mode=adapter_mode)

    def test_fix_edge_captures_once(self):
        """h-fix の go が真の 1 周目 → 盤面の隣に写しを作る。呼び直しても写し直さない"""
        self.fix_ready()
        got = self.edge("fix")
        self.assertTrue(got["go"], got)
        man = self.board.parent / fixture.DIR / fixture.MANIFEST
        self.assertTrue(man.is_file())
        before = man.read_bytes()
        self.edge("fix")
        self.assertEqual(man.read_bytes(), before)

    def test_fix_edge_capture_failure_does_not_stop(self):
        """写せない（OSError）→ trace に fixture_capture_failed の 1 行を残して、go はそのまま"""
        self.fix_ready()
        for err in (OSError("disk full"), ValueError("state.json が壊れた")):
            with mock.patch.object(fixture, "capture", side_effect=err):
                got = self.edge("fix")
            self.assertTrue(got["go"], got)
            self.assertFalse(got["stop"], got)
        rows = trace_ops(self.board, "fixture_capture_failed")
        self.assertEqual(len(rows), 2)
        self.assertIn("disk full", json.dumps(rows[0], ensure_ascii=False))
        self.assertIn("ValueError", json.dumps(rows[1], ensure_ascii=False))

    def test_fix_edge_skips_capture_on_fixture_board(self):
        """固定材料から始めた盤面（start の控えに fixture）の h-fix は写さない"""
        _, src = self.captured()
        other = self.clone_same_tree()
        new_board = self.tmp / "b2" / "art" / "board"
        self.adopt(src, other, new_board)
        got = self.edge("fix", board=new_board, repo=other)
        self.assertTrue(got["go"], got)
        self.assertFalse((new_board.parent / fixture.DIR).exists())
        self.assertIsNone(fixture.capture(new_board, other, run_id="run-2", pack_root=PACK), "固定材料の盤面は写さない")

    def test_judge_and_mat_on_fixture_board(self):
        """固定材料の盤面: h-judge は役がまだ起きていない run でも包みの記録の無さで止めない（最初の役は修正役）、h-mat の go は
        偽（判定は済んでいる。判定のブロックを回さない）"""
        _, src = self.captured()
        other = self.clone_same_tree()
        new_board = self.tmp / "b2" / "art" / "board"
        self.adopt(src, other, new_board)
        got = self.edge("judge", board=new_board, repo=other, adapter_mode="")
        self.assertEqual((got["stop"], got["go"]), (False, True), got)
        got = self.edge("mat", board=new_board, repo=other)
        self.assertEqual((got["stop"], got["go"]), (False, False), got)

    def test_review_checks_adapter_on_fixture_board(self):
        """固定材料の盤面で包みを求める run（adapter が空）に包みの起動の行が無い → 修正のブロックと再審の後の境の節 h-review で
        works:adapter として止める（h-judge では止めない）"""
        _, src = self.captured()
        other = self.clone_same_tree()
        new_board = self.tmp / "b2" / "art" / "board"
        self.adopt(src, other, new_board)
        self.assertFalse(self.edge("judge", board=new_board, repo=other, adapter_mode="")["stop"])
        got = self.edge("review", board=new_board, repo=other, adapter_mode="")
        self.assertEqual((got["stop"], got["go"]), (True, False), got)
        stop = json.loads((new_board / "state.json").read_text(encoding="utf-8"))["stop"]
        self.assertEqual(stop["by"], stopby.ADAPTER)


if __name__ == "__main__":
    unittest.main()
