"""役の渡し方（会社の形の設計 4.7・4.8）: 会社の形の役の項目（role ノード）、部署を起動するときの --settings・--model・--effort と gh の
アカウントの属性（launch と入口の --task）、役の本文と GH_TOKEN の行を足す SessionStart のフック（role_hook）。git（tests/fakegit.py）・herdr・claude は偽物で回す。"""

import contextlib
import io
import json
import os
import pathlib
import re
import shlex
import shutil
import tempfile
import unittest
import urllib.parse
from unittest import mock

from . import DISPATCH, fakegit
from .test_dispatch import FakeHerdr, gitx_source
from . import test_task
import claudex
import orders
import role_hook
import wake_hook
from nodes import deliver, launch, provision, role, tree

SHAPE = '''
name = "試しの会社"
gh_user = "gh-co"

[[roles]]
name = "調べ役"
instructions = "結論と原典の一句を返す。"
model = "haiku"
effort = "low"
deliver = ["結論", "差分", "試験"]
settings = { enabledPlugins = { "pr-review-toolkit@m" = false }, permissions = { deny = ["Artifact", "Workflow"] }, worktree = { bgIsolation = "auto" } }

[[roles]]
name = "出荷役"
'''


def write(path, text):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(path).write_text(text, encoding="utf-8")
    return str(path)


class Shape(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_roles_and_gh_user_are_read(self):
        got = role.load(write(f"{self.d}/c.toml", SHAPE))
        self.assertEqual(got["problems"], [])
        self.assertEqual(got["gh_user"], "gh-co")
        self.assertEqual(got["roles"]["調べ役"]["model"], "haiku")
        self.assertEqual(got["roles"]["調べ役"]["instructions"], "結論と原典の一句を返す。")
        self.assertEqual(got["roles"]["調べ役"]["deliver"], ["結論", "差分", "試験"])
        self.assertEqual(got["roles"]["調べ役"]["effort"], "low")
        self.assertEqual(got["roles"]["出荷役"], {"name": "出荷役", "instructions": None, "model": None, "effort": None, "account": None, "settings": None,
                                                 "deliver": None, "deliver_check": None, "persistent": False, "fresh": False, "machine": False, "tools": [],
                                                 "holders": None, "ask_holders": None, "ask_check": None, "keepalive": None, "odd": []})

    def test_no_file_is_empty_and_broken_shapes_are_problems_but_others_are_read(self):
        self.assertEqual(role.load(None), {"roles": {}, "gh_user": None, "shared": None, "default_role": None, "desk_role": None,
                                                 "former": {}, "problems": []})
        got = role.load(write(f"{self.d}/c.toml", '''gh_user = 3
[[roles]]
instructions = "名前が無い"
[[roles]]
name = "a"
settings = "文字"
[[roles]]
name = "b"
[[roles]]
name = "b"
model = "x"
'''))
        self.assertEqual(list(got["roles"]), ["b"])
        self.assertIsNone(got["roles"]["b"]["model"])   # 2 度目は使わない
        self.assertEqual(len(got["problems"]), 4, got["problems"])
        self.assertIn("TOML", role.load(write(f"{self.d}/bad.toml", "[[roles]"))["problems"][0])

    def test_roles_by_name_and_misplaced_deliver_are_problems_not_silence(self):
        got = role.load(write(f"{self.d}/old.toml", '[roles."サブエージェント"]\ndeliver = ["結論"]\n'))
        self.assertEqual(got["roles"], {})
        self.assertIn('[roles."役"] の形で書いている（サブエージェント）', got["problems"][0])
        self.assertIn("[[roles]] の項目", got["problems"][0])
        got = role.load(write(f"{self.d}/c.toml", '''[[roles]]
name = "a"
deliver = "結論"
[[roles]]
name = "b"
[roles.settings]
deliver = ["結論"]
deliver_check = "x"
[[roles]]
name = "c"
deliver_check = ""
'''))
        self.assertEqual(list(got["roles"]), ["b"])
        self.assertIn("deliver の形が違う", got["problems"][0])
        self.assertIn("deliver が [roles.settings] の中に入っている", got["problems"][1])
        self.assertIn("deliver_check が [roles.settings] の中に入っている", got["problems"][2])
        self.assertIn("deliver_check の形が違う", got["problems"][3])
        self.assertIsNone(got["roles"]["b"]["deliver_check"])

    def test_pick_stops_only_on_an_explicit_role_missing_from_a_shape_that_has_roles(self):
        shape = role.load(write(f"{self.d}/c.toml", SHAPE))
        self.assertEqual(role.pick(shape, "調べ役", True)[0]["name"], "調べ役")
        self.assertIn("在る役: 調べ役, 出荷役", role.pick(shape, "調べやく", True)[1])
        self.assertEqual(role.pick(shape, "サブエージェント", False), (None, None))
        self.assertEqual(role.pick(role.load(None), "何か", True), (None, None))

    def test_default_role_and_resident_are_read_and_checked(self):
        got = role.load(write(f"{self.d}/d.toml", 'default_role = "b"\n[[roles]]\nname = "a"\npersistent = true\n[[roles]]\nname = "b"\n'))
        self.assertEqual((got["default_role"], got["roles"]["a"]["persistent"], got["roles"]["b"]["persistent"], got["problems"]),
                         ("b", True, False, []))
        self.assertEqual(role.default(got, "作業"), ("b", None))
        # 前の版の鍵 resident も同じ意味で読む（persistent が有ればそちら）
        got = role.load(write(f"{self.d}/r.toml", '[[roles]]\nname = "a"\nresident = true\n[[roles]]\nname = "b"\nresident = true\npersistent = false\n'))
        self.assertEqual((got["roles"]["a"]["persistent"], got["roles"]["b"]["persistent"], got["problems"]), (True, False, []))
        got = role.load(write(f"{self.d}/e.toml", 'default_role = "無い"\n[[roles]]\nname = "a"\npersistent = "yes"\n'
                                                  '[[roles]]\nname = "c"\n'))
        self.assertIsNone(got["default_role"])
        self.assertEqual(list(got["roles"]), ["c"])
        self.assertIn("persistent の形が違う", got["problems"][0])
        self.assertIn("default_role の役 無い が [[roles]] に無い", got["problems"][1])
        name, why = role.default(got, "作業")   # 会社の形に無い既定の役は止める（英語の役の名前の会社で、役の無い部署を立てない）
        self.assertEqual(name, "作業")
        self.assertIn("在る役: c", why)
        self.assertEqual(role.default(role.load(None), "作業"), ("作業", None))   # 役を書いていない会社では注記を出さない

    def test_settings_keep_the_role_keys_and_the_fixed_keys_win(self):
        r = role.load(write(f"{self.d}/c.toml", SHAPE))["roles"]["調べ役"]
        self.assertEqual(role.settings_for(r), {"enabledPlugins": {"pr-review-toolkit@m": False},
                                                "permissions": {"deny": ["Artifact", "Workflow"]},
                                                "worktree": {"bgIsolation": "none"}})
        self.assertEqual(role.settings_for(None), {"worktree": {"bgIsolation": "none"}})
        path = role.write_settings(self.d, role.settings_for(r))
        self.assertEqual(json.loads(pathlib.Path(path).read_text(encoding="utf-8")), role.settings_for(r))

    def test_users_own_gh_user_comes_first(self):
        self.assertEqual(role.gh_user(None, {"gh_user": "co"}), ("co", None))
        self.assertEqual(role.gh_user("me", {"gh_user": None}), ("me", None))
        user, note = role.gh_user("me", {"gh_user": "co"})
        self.assertEqual(user, "me")
        self.assertIn("co", note)

    def test_turning_this_plugin_off_is_warned(self):
        r = {"name": "x", "settings": {"enabledPlugins": {"works-dispatch@m": False, "other@m": False}}}
        self.assertEqual(len(role.warnings(r)), 1)
        self.assertEqual(role.warnings({"name": "x", "settings": {"enabledPlugins": {"works-dispatch@m": True}}}), [])
        self.assertEqual(role.warnings(None), [])

    def test_env_line_fetches_the_key_each_time_and_never_holds_it(self):
        self.assertEqual(role.env_line("gh-co"), 'export GH_TOKEN="$(gh auth token --user gh-co || echo gh-user-not-logged-in)"')
        self.assertEqual(shlex.split(role.env_line("a b")),
                         ["export", "GH_TOKEN=$(gh auth token --user 'a b' || echo gh-user-not-logged-in)"])

    def test_context_is_one_line_when_the_role_has_no_text(self):
        self.assertEqual(role.context("調べ役", {"instructions": "短く"}, "会社"), "この会話は会社「会社」の部署で、役は「調べ役」。\n短く")
        self.assertEqual(role.context("x", None, "会社"), "この会話は会社「会社」の部署で、役は「x」。")

    def test_shared_text_goes_before_every_role_text_but_not_to_the_head_office(self):
        # 役をまたぐ会社の決まりを、役ごとに写さず 1 か所に書く（works-factory の会社で 6 つの役に同じ文を写した。受付 6ea42d）
        shape = role.load(write(f"{self.d}/c.toml", 'shared_instructions = """\n試験は触った所だけ。\n"""\n' + SHAPE))
        self.assertEqual((shape["problems"], shape["shared"]), ([], "試験は触った所だけ。"))
        self.assertEqual(role.context("調べ役", shape["roles"]["調べ役"], "会社", shared=shape["shared"]),
                         "この会話は会社「会社」の部署で、役は「調べ役」。\n試験は触った所だけ。\n結論と原典の一句を返す。")
        self.assertEqual(role.context("x", None, "会社", shared=shape["shared"]), "この会話は会社「会社」の部署で、役は「x」。\n試験は触った所だけ。")
        self.assertEqual(role.context("窓口", None, "会社", head_office=True, shared=shape["shared"]),
                         "この会話は会社「会社」の本社の会話で、役は「窓口」。")
        bad = role.load(write(f"{self.d}/d.toml", "shared_instructions = 1\n" + SHAPE))
        self.assertIsNone(bad["shared"])
        self.assertIn("shared_instructions が文字列で無い", bad["problems"][0])


class Seat(unittest.TestCase):
    def test_fresh_is_read_and_shown_with_residency(self):
        d = tempfile.mkdtemp()
        got = role.load(write(f"{d}/c.toml", '[[roles]]\nname = "担当"\npersistent = true\nfresh = true\n'
                                             '[[roles]]\nname = "相談"\npersistent = true\n[[roles]]\nname = "変"\nfresh = "yes"\n'))
        self.assertEqual((got["roles"]["担当"]["fresh"], got["roles"]["相談"]["fresh"]), (True, False))
        self.assertNotIn("変", got["roles"])
        self.assertIn("persistent・resident・fresh・machine は true か false", got["problems"][0])
        # herdr の作業場の印に、永続かエフェメラルかと、会話を引き継ぐか毎回クリアするかを出す。比べるのはキーの seat、見せるのは語の kind。ペインの表示名は役だけ
        from nodes import sync
        self.assertEqual(sync.seat_of({"role": "担当", "lifecycle": "persistent", "fresh": "true"}), "persistent-fresh")
        self.assertEqual(sync.seat_of({"role": "相談", "lifecycle": "persistent"}), "persistent-carry")
        self.assertEqual(sync.seat_of({"role": "作業", "lifecycle": "ephemeral"}), "ephemeral")
        self.assertIsNone(sync.seat_of({}))
        self.assertEqual(sync.seat_tokens("persistent-fresh"), {"kind": "永続・毎回クリア", "seat": "persistent-fresh"})
        self.assertEqual(sync.op("p", {"role": "担当", "lifecycle": "persistent", "name": "割り振り"}, False)["display_agent"], "担当")


class ModelAndEffort(unittest.TestCase):
    """役の model と effort: 省けばアカウントの既定、値を書けばその値、effort の inherit は呼んだ会話の今の effort（CLAUDE_EFFORT）。"""

    def roles(self, body):
        d = tempfile.mkdtemp()
        return role.load(write(f"{d}/c.toml", body))

    def test_effort_values_are_checked_and_unknown_ones_drop_the_role(self):
        # claude は知らない --effort を注意だけで既定に戻す（裏の会話では黙って）ので、書き損じは読むときに弾く
        got = self.roles('[[roles]]\nname = "a"\neffort = "xhigh"\n[[roles]]\nname = "b"\neffort = "hihg"\n'
                         '[[roles]]\nname = "c"\neffort = "inherit"\n')
        self.assertEqual((got["roles"]["a"]["effort"], got["roles"]["c"]["effort"]), ("xhigh", "inherit"))
        self.assertNotIn("b", got["roles"])
        [problem] = got["problems"]
        self.assertIn("effort は low・medium・high・xhigh・max・ultracode・inherit のどれか", problem)

    def test_model_inherit_is_not_made(self):
        # 頼み元の会話の今のモデルを外から読む口が無いので、model の inherit は作らず、書き損じと同じに役を外して知らせる
        got = self.roles('[[roles]]\nname = "a"\nmodel = "inherit"\n')
        self.assertNotIn("a", got["roles"])
        self.assertIn("model の inherit は作っていない", got["problems"][0])

    def test_launch_flags(self):
        r = {"name": "担当", "model": "opus", "effort": "max"}
        self.assertEqual(role.launch_flags(r, {"CLAUDE_EFFORT": "low"}), ("opus", "max", None))
        self.assertEqual(role.launch_flags(None, {"CLAUDE_EFFORT": "low"}), (None, None, None))
        self.assertEqual(role.launch_flags({**r, "effort": "inherit"}, {"CLAUDE_EFFORT": "low"}), ("opus", "low", None))
        model, effort, note = role.launch_flags({**r, "effort": "inherit"}, {})
        self.assertEqual((model, effort), ("opus", None))
        self.assertIn("CLAUDE_EFFORT が無い", note)

    def test_account_is_a_name_and_the_duty_comes_first(self):
        got = role.load("t", '[[roles]]\nname = "写しの後始末"\nmodel = "sonnet"\naccount = " cheapest "\n'
                             '[[roles]]\nname = "作業"\naccount = ""\n')
        r = got["roles"]["写しの後始末"]
        self.assertEqual(r["account"], "cheapest")
        self.assertNotIn("作業", got["roles"])   # 空の名前は形の違う値として役を外す
        self.assertIn("account の形が違う", got["problems"][0])
        self.assertEqual(role.launch_account(r), ("cheapest", "役 写しの後始末"))
        self.assertEqual(role.launch_account(r, {"name": "写し", "account": "p2"}), ("p2", "受け持ち 写し"))
        self.assertEqual(role.launch_account(r, {"name": "写し", "account": None}), ("cheapest", "役 写しの後始末"))
        self.assertEqual(role.launch_account(None), (None, None))
        # 起動したときの値（company.launched）には入れない（名指しと違うアカウントで立った fresh の部署を、頼みのたびに起動し直さない）
        self.assertEqual(role.launch_key(r), role.launch_key({**r, "account": None}))
        self.assertEqual(json.loads(role.launch_key(r)), {"model": "sonnet", "effort": None})

    def test_launch_key_keeps_inherit_unresolved_and_takes_the_duty_first(self):
        # 毎回クリアする部署の待ち受けが比べる字。inherit は解かない（呼んだ会話の effort が替わっても起動し直さない）
        r = {"name": "担当", "model": "opus", "effort": "inherit"}
        self.assertEqual(json.loads(role.launch_key(r)), {"model": "opus", "effort": "inherit"})
        self.assertEqual(json.loads(role.launch_key(r, {"name": "割り振り", "model": "sonnet", "effort": None})),
                         {"model": "sonnet", "effort": "inherit"})
        self.assertEqual(json.loads(role.launch_key(None)), {"model": None, "effort": None})

    def test_duty_is_found_by_the_same_name_or_by_the_head_of_a_one_off_name(self):
        # 永続の部署は名前が受け持ちと同じ。一度きりの部署は「<受け持ち>：<何をするか>」。同じ名前の受け持ちが先
        skills = [{"name": "調べもの"}, {"name": "調べもの：常設"}, {"name": "手入れ"}]
        self.assertIs(role.duty_of(skills, "調べもの"), skills[0])
        self.assertIs(role.duty_of(skills, "調べもの：原典の確かめ"), skills[0])
        self.assertIs(role.duty_of(skills, "調べもの：常設"), skills[1])
        self.assertIs(role.duty_of(skills, "調べもの：常設：二つ目"), skills[1])
        for name in ("調べものの続き", "：調べもの", "調べもの:半角", "別の仕事：調べもの", None, ""):
            self.assertIsNone(role.duty_of(skills, name), name)

    def test_duty_settings_are_laid_over_the_roles_and_keyed_for_restart(self):
        r = {"name": "作業", "settings": {"permissions": {"deny": ["AskUserQuestion"]}, "promptCacheTtl": "1h"}}
        duty = {"name": "調べもの", "settings": {"promptCacheTtl": "5m", "permissions": {"allow": ["WebFetch"]},
                                                  "worktree": {"bgIsolation": "auto"}}}
        self.assertEqual(role.settings_for(r, duty), {"permissions": {"deny": ["AskUserQuestion"], "allow": ["WebFetch"]},
                                                      "promptCacheTtl": "5m", "worktree": {"bgIsolation": "none"}})
        self.assertEqual(role.settings_for(None, duty)["promptCacheTtl"], "5m")
        self.assertEqual(role.settings_for(r, {"name": "手入れ", "settings": None}), role.settings_for(r))
        # 待ち受けが比べる字にも重ねた設定が入る（受け持ちの設定を替えれば起動し直す）。どちらにも無ければ settings を書かない
        self.assertEqual(json.loads(role.launch_key(r, duty))["settings"]["promptCacheTtl"], "5m")
        self.assertEqual(json.loads(role.launch_key({"name": "作業"}, {"name": "調べもの", "settings": None})), {"model": None, "effort": None})

    def test_keepalive_is_read_in_its_forms_and_a_bad_value_is_dropped_with_a_note(self):
        problems = []
        self.assertIsNone(role.parse_keepalive(None, "w", problems))
        self.assertIs(role.parse_keepalive(False, "w", problems), False)
        self.assertEqual(role.parse_keepalive(True, "w", problems), {"every": None, "text": None})
        self.assertEqual(role.parse_keepalive({"every": "4m", "text": " 見る "}, "w", problems), {"every": 240, "text": "見る"})
        self.assertEqual(role.parse_keepalive({"every": 200}, "w", problems), {"every": 200, "text": None})
        self.assertEqual(problems, [])
        for bad in ({"every": "4 min"}, {"every": 0}, {"every": True}, {"text": ""}, "4m", 240):
            got = []
            self.assertIsNone(role.parse_keepalive(bad, "w", got), bad)
            self.assertEqual(len(got), 1, bad)

    def test_keepalive_takes_the_duty_over_the_role_and_its_interval_from_the_cache_lifetime(self):
        on = {"every": None, "text": None}
        r = {"name": "作業", "keepalive": on, "settings": {"promptCacheTtl": "1h"}}
        five = {"name": "調べもの", "settings": {"promptCacheTtl": "5m"}, "keepalive": None}
        # 寿命から余裕を引いた間隔。続けて送るのは、読みの値段が書き直し 1 回に届くまで（5 分は 1.25 / 0.1、1 時間は 2 / 0.1）
        self.assertEqual({k: v for k, v in role.keepalive_for(r, five).items() if k != "text"},
                         {"every": 300 - role.KEEPALIVE_MARGIN, "ttl": 300, "limit": 13, "written": False})
        self.assertEqual({k: v for k, v in role.keepalive_for(r).items() if k != "text"},
                         {"every": 3600 - role.KEEPALIVE_MARGIN, "ttl": 3600, "limit": 20, "written": False})
        self.assertEqual(role.keepalive_for({"name": "作業", "keepalive": on})["ttl"], 3600)   # 寿命を書かなければ 1 時間と見る
        self.assertEqual(role.keepalive_for(r)["text"], role.KEEPALIVE_TEXT)
        # 受け持ちの表は鍵ごとに役の表に重なり、false は役の物を止める
        got = role.keepalive_for({"name": "作業", "keepalive": {"every": 100, "text": "役の文"}},
                                 {"name": "調べもの", "keepalive": {"every": None, "text": "受け持ちの文"}})
        self.assertEqual((got["every"], got["text"]), (100, "受け持ちの文"))
        self.assertIsNone(role.keepalive_for(r, {"name": "手入れ", "keepalive": False}))
        self.assertIsNone(role.keepalive_for({"name": "作業"}, five))

    def test_keepalive_reads_the_cache_lifetime_in_the_order_claude_code_does_and_skips_what_it_cannot_tell(self):
        on = {"name": "作業", "keepalive": {"every": None, "text": None}}
        five, hour = dict(on, settings={"promptCacheTtl": "5m"}), dict(on, settings={"promptCacheTtl": "1h"})
        ttl = lambda r, env: (role.keepalive_for(r, env=env) or {}).get("ttl")
        # 5 分に決める環境変数 → 寿命の環境変数 → 設定 → 1 時間を頼む環境変数 → 既定
        self.assertEqual(ttl(hour, {"FORCE_PROMPT_CACHING_5M": "1", "CLAUDE_CODE_PROMPT_CACHE_TTL": "1h"}), 300)
        self.assertEqual(ttl(hour, {"CLAUDE_CODE_PROMPT_CACHE_TTL": "5m"}), 300)
        self.assertEqual(ttl(five, {"ENABLE_PROMPT_CACHING_1H": "1"}), 300)
        self.assertEqual(ttl(on, {"ENABLE_PROMPT_CACHING_1H": "1"}), 3600)
        self.assertEqual(ttl(on, {}), 3600)
        self.assertEqual(role.keepalive_for(five, env={"FORCE_PROMPT_CACHING_5M": "1"}, read=0.05)["limit"], 25)
        # 寿命が無い・分からない・間が寿命より短くないなら、送っても切れた後に届くので送らず、訳を注記に出す
        for r, env, why in ((five, {"DISABLE_PROMPT_CACHING": "1"}, "DISABLE_PROMPT_CACHING"),
                            (five, {"CLAUDE_CODE_PROMPT_CACHE_TTL": "10m"}, "'10m'"),
                            (dict(on, settings={"promptCacheTtl": "10m"}), {}, "'10m'"),
                            (dict(five, keepalive={"every": 300, "text": None}), {}, "300 秒")):
            notes = []
            self.assertIsNone(role.keepalive_for(r, notes=notes, env=env), (r, env))
            self.assertIn(why, notes[0])

    def test_keepalive_is_read_from_the_shape_for_roles_and_duties(self):
        d = tempfile.mkdtemp()
        got = role.load(write(f"{d}/c.toml", '[[roles]]\nname = "作業"\n[roles.keepalive]\nevery = "3m"\n'
                                             '[[roles]]\nname = "担当"\nkeepalive = 5\n'))
        self.assertEqual(got["roles"]["作業"]["keepalive"], {"every": 180, "text": None})
        self.assertIsNone(got["roles"]["担当"]["keepalive"])
        self.assertEqual(len(got["problems"]), 1)
        problems = []
        skills = tree._skills([{"name": "調べもの", "keepalive": {"text": "待つ"}}, {"name": "手入れ", "keepalive": False}],
                              "w", problems)
        self.assertEqual([s["keepalive"] for s in skills], [{"every": None, "text": "待つ"}, False])

    def test_flow_rank_puts_carry_over_then_standing_by_the_duties_then_per_task_then_the_rest(self):
        # herdr の作業場の並びと --tree の部署の並びが同じ鍵を使う（持ち主 2026-10-17 の案 A）
        duties = ["ノートの手入れ", "調べもの"]
        rows = {"社長室": {"role": "相談", "name": "社長室", "lifecycle": "persistent"},
                "調べもの": {"role": "担当", "name": "調べもの", "lifecycle": "persistent", "fresh": "true"},
                "ノートの手入れ": {"role": "担当", "name": "ノートの手入れ", "lifecycle": "persistent", "fresh": "true"},
                "新しい担当": {"role": "担当", "name": "新しい担当", "lifecycle": "persistent", "fresh": "true"},
                "作業：1": {"role": "作業", "name": "作業：1", "lifecycle": "ephemeral"}, "手で開いた": {}}
        self.assertEqual(sorted(rows, key=lambda n: role.flow_rank(rows[n], duties)),
                         ["社長室", "ノートの手入れ", "調べもの", "新しい担当", "作業：1", "手で開いた"])

    def test_launch_flags_take_the_duty_before_the_role(self):
        # 決める順はフィールドごとに、部署（受け持ち）・役・アカウントの既定。受け持ちに無いフィールドは役の値
        r = {"name": "担当", "model": "opus", "effort": "max"}
        self.assertEqual(role.launch_flags(r, {}, {"name": "割り振り", "model": "sonnet", "effort": "low"}), ("sonnet", "low", None))
        self.assertEqual(role.launch_flags(r, {}, {"name": "割り振り", "model": None, "effort": "low"}), ("opus", "low", None))
        self.assertEqual(role.launch_flags(None, {}, {"name": "割り振り", "model": "haiku", "effort": None}), ("haiku", None, None))
        self.assertEqual(role.launch_flags(r, {"CLAUDE_EFFORT": "xhigh"}, {"name": "割り振り", "model": None, "effort": "inherit"}),
                         ("opus", "xhigh", None))
        _, effort, note = role.launch_flags(r, {}, {"name": "割り振り", "model": None, "effort": "inherit"})
        self.assertIsNone(effort)
        self.assertIn("部署 割り振り の effort は inherit", note)


class Launch(unittest.TestCase):
    ROW = {"account": {"command": "claude-a1"}, "label": None}

    def started(self, posix, **kw):
        h = FakeHerdr()
        got = launch.start_background(self.ROW, "P0", "直し", "s.json", "頼み", h, posix=posix, pause=lambda: None, **kw)
        return got, [w[2] for w in h.writes if w[0] == "run"][0]

    def test_model_is_put_before_the_first_text(self):
        got, command = self.started(True, model="haiku")
        self.assertEqual(got["status"], "sent")
        self.assertEqual(shlex.split(command), ["claude-a1", "--bg", "--name", "直し", "--settings", "s.json", "--model", "haiku", "頼み"])

    def test_effort_is_put_after_the_model(self):
        _, command = self.started(True, model="haiku", effort="low")
        self.assertEqual(shlex.split(command), ["claude-a1", "--bg", "--name", "直し", "--settings", "s.json", "--model", "haiku",
                                                "--effort", "low", "頼み"])
        _, command = self.started(True, effort="max")
        self.assertEqual(shlex.split(command)[-3:], ["--effort", "max", "頼み"])

    def test_without_model_the_command_is_as_before(self):
        _, command = self.started(True)
        self.assertEqual(shlex.split(command), ["claude-a1", "--bg", "--name", "直し", "--settings", "s.json", "頼み"])
        _, command = self.started(False, model="haiku")
        self.assertIn('--model "haiku"', command)


class Hook(unittest.TestCase):
    def setUp(self):
        self.g, self.src, root = fakegit.world()
        fakegit.wire(self, self.g, role_hook, orders, wake_hook)
        self.place = self.g.add_worktree(str(pathlib.Path(root) / "dept"), "dept/a", "origin/main")
        self.env = {"WORKS_DISPATCH_CONFIG": str(pathlib.Path(root).parent / "conf" / "dispatch.toml"),
                    "TMPDIR": tempfile.mkdtemp()}   # 会話に足した文の控えの置き場

    def test_clear_compact_and_resume_rewrite_the_department_session_and_keep_the_job(self):
        # /clear で会話の id が変わる。古い id のままだと --ask が動き出しを見られず、Stop フックが部署の会話を見分けなかった。
        # 裏の会話の短い id（attach に渡す）は /clear の後も変わらないので、前の版の部署は古い id の頭を job に残す
        provision.mark(self.place, self.src, {"role": "担当", "session": "8c4a1102-aaaa", "ask": "X", "boss": "窓口"}, self.g)
        role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "a5b0bc07-bbbb", "source": "clear"})), self.env)
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual((attrs["session"], attrs["job"]), ("a5b0bc07-bbbb", "8c4a1102"))
        # 書き直した後は、Stop フックがこの会話を部署の会話と見て、納品していない頼みを差し戻す
        self.assertIsNotNone(deliver.stop_verdict({"session_id": "a5b0bc07-bbbb"}, attrs, 0, "run"))
        for source in ("compact", "resume"):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": f"s-{source}", "source": source})), self.env)
            attrs = self.g.worktree_attrs(self.place)
            self.assertEqual((attrs["session"], attrs["job"]), (f"s-{source}", "8c4a1102"))

    def test_a_subagent_compacting_gets_no_role_text_and_keeps_the_department_session(self):
        # サブエージェントの compact の SessionStart も、会話の id は本体の物で届く。役の本文を足すとサブエージェントが部署を名乗る
        write(pathlib.Path(self.src) / ".claude" / "company.toml", SHAPE)
        provision.mark(self.place, self.src, {"role": "調べ役", "session": "s-dept", "job": "j-dept"}, self.g)

        def start(**extra):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "s-dept", "source": "compact", **extra})),
                               self.env)
            return out.getvalue()
        self.assertEqual(start(agent_id="a9de"), "")
        self.assertIn("役は「調べ役」", start())   # 本体の compact には足す
        provision.mark(self.place, self.src, {"session": "s-dept"}, self.g)
        start(agent_id="a9de")
        self.assertEqual(self.g.worktree_attrs(self.place)["session"], "s-dept")

    def test_new_talks_and_the_head_office_keep_the_department_session(self):
        # 部署の場所で人が別の会話を起動しても（startup）、本社で持ち主の会話が /clear しても、部署の会話の id は替えない
        provision.mark(self.place, self.src, {"role": "担当", "session": "s-dept"}, self.g)
        role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "s-other", "source": "startup"})), self.env)
        self.assertEqual(self.g.worktree_attrs(self.place)["session"], "s-dept")
        provision.mark(self.src, self.src, {"role": "窓口", "session": "s-desk"}, self.g)
        role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-mine", "source": "clear"})), self.env)
        self.assertEqual(self.g.worktree_attrs(self.src)["session"], "s-desk")

    def test_department_gets_its_role_text_and_other_places_get_nothing(self):
        write(pathlib.Path(self.src) / ".claude" / "company.toml", SHAPE)
        self.assertIsNone(role_hook.text_for(self.place, self.env))   # 役の属性が無い
        provision.mark(self.place, self.src, {"role": "調べ役"}, self.g)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「調べ役」。\n結論と原典の一句を返す。")
        self.assertIsNone(role_hook.text_for(self.src, self.env))      # 本社
        provision.mark(self.src, self.src, {"role": "窓口"}, self.g)     # --desk で名付けた本社の窓口は、部署と書かない
        self.assertEqual(role_hook.text_for(self.src, self.env), "この会話は会社「試しの会社」の本社の会話で、役は「窓口」。")
        self.assertIsNone(role_hook.text_for(tempfile.mkdtemp(), self.env))   # git でない

    def test_shared_text_reaches_departments_but_not_the_head_office_desk(self):
        write(pathlib.Path(self.src) / ".claude" / "company.toml", 'shared_instructions = "試験は触った所だけ。"\n' + SHAPE)
        provision.mark(self.place, self.src, {"role": "調べ役"}, self.g)
        self.assertEqual(role_hook.text_for(self.place, self.env),
                         "この会話は会社「試しの会社」の部署で、役は「調べ役」。\n試験は触った所だけ。\n結論と原典の一句を返す。")
        provision.mark(self.src, self.src, {"role": "窓口"}, self.g)
        self.assertEqual(role_hook.text_for(self.src, self.env), "この会話は会社「試しの会社」の本社の会話で、役は「窓口」。")

    def test_role_text_comes_from_the_default_branch_when_the_head_office_is_on_an_old_branch(self):
        self.g.push_origin("main", {".claude/company.toml": SHAPE}, "company")   # 会社の形はメインブランチに在る
        self.g.fetch(self.src, "main")
        self.g.local["old"] = self.g.local["main"]
        self.g.heads[self.src] = "old"   # 元の clone はほかの会話が古いブランチで使っている（会社の形を持たない）
        provision.mark(self.place, self.src, {"role": "調べ役"}, self.g)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「調べ役」。\n結論と原典の一句を返す。")
        # --ask・--deliver の読み方（orders.shape_role）も同じ物を読む
        got, problems = orders.shape_role(self.src, None, "調べ役", self.g)
        self.assertEqual((got["instructions"], problems), ("結論と原典の一句を返す。", []))

    def test_shape_outside_the_repo_is_read_and_a_missing_role_gets_only_the_head_line(self):
        conf = pathlib.Path(self.env["WORKS_DISPATCH_CONFIG"]).parent
        write(conf / "companies" / (urllib.parse.quote(os.path.realpath(self.src), safe="") + ".toml"), SHAPE)
        provision.mark(self.place, self.src, {"role": "出荷役"}, self.g)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「出荷役」。")
        provision.mark(self.place, self.src, {"role": "無い役"}, self.g)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「無い役」。")

    def test_shape_beside_the_departments_own_config_is_read(self):
        other = pathlib.Path(tempfile.mkdtemp()) / "mine.toml"
        write(other.parent / "companies" / (urllib.parse.quote(os.path.realpath(self.src), safe="") + ".toml"), SHAPE)
        provision.mark(self.place, self.src, {"role": "調べ役", "config": str(other)}, self.g)
        self.assertIn("結論と原典の一句", role_hook.text_for(self.place, self.env))

    def test_gh_user_is_put_into_the_env_file_once_without_the_key(self):
        provision.mark(self.place, self.src, {"role": "調べ役", "gh-user": "gh-co"}, self.g)
        envfile = pathlib.Path(tempfile.mkdtemp()) / "env.sh"
        envfile.write_bytes(b"export A=1\n")   # write_text は Windows で \r\n にする
        env = {**self.env, "CLAUDE_ENV_FILE": str(envfile)}
        for _ in range(2):   # resume で 2 度走っても 1 行
            with contextlib.redirect_stdout(io.StringIO()):
                role_hook.main(io.StringIO(json.dumps({"cwd": self.place})), env)
        self.assertEqual(envfile.read_bytes().decode("utf-8"), "export A=1\n" + role.env_line("gh-co") + "\n")   # Windows でも \r 無し
        # 属性が無い・ファイルの場所が無いなら書かない
        role_hook.put_env({"role": "x"}, env)
        role_hook.put_env({"gh-user": "gh-co"}, self.env)
        self.assertEqual(len(envfile.read_text(encoding="utf-8").splitlines()), 2)

    def test_broken_shape_does_not_stop_the_conversation(self):
        write(pathlib.Path(self.src) / ".claude" / "company.toml", "[[roles]")
        provision.mark(self.place, self.src, {"role": "調べ役"}, self.g)
        self.assertIn("読めない所がある", role_hook.text_for(self.place, self.env))

    def test_main_prints_the_hook_output_only_for_a_department(self):
        provision.mark(self.place, self.src, {"role": "調べ役"}, self.g)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "hook_event_name": "SessionStart"})), self.env)
        got = json.loads(out.getvalue())["hookSpecificOutput"]
        self.assertEqual(got["hookEventName"], "SessionStart")
        self.assertIn("調べ役", got["additionalContext"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.src})), self.env)
        self.assertEqual(out.getvalue(), "")

    def test_the_head_office_desk_session_follows_a_clear_in_the_same_process_only(self):
        # 段取り（--desk の会話）は区切りで /clear する。--desk が書いた会話の処理の番号の処理なら、新しい id に書き直す
        provision.mark(self.src, self.src, {"role": "窓口", "session": "s-desk", "pid": "999999999"}, self.g)
        role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-other", "source": "clear"})), self.env)
        self.assertEqual(self.g.worktree_attrs(self.src)["session"], "s-desk")   # 持ち主のほかの会話の /clear
        provision.mark(self.src, self.src, {"pid": str(os.getpid())}, self.g)   # フックは会話の処理の子で走る（ここではこの処理）
        write(pathlib.Path(self.src) / ".claude" / "company.toml", '[[roles]]\nname = "窓口"\ninstructions = "頼みを配る。"\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-new", "source": "clear"})), self.env)
        self.assertEqual(self.g.worktree_attrs(self.src)["session"], "s-new")
        self.assertIn("席はこの会話に引き継いだ", out.getvalue())   # 窓口は空にした後に --desk を打ち直して確かめなくてよい
        self.assertIsNone(role_hook.changed({"cwd": self.src, "session_id": "s-new"}, self.env))   # 次の発言で役の本文を足し直さない

    def test_only_the_desk_seat_gets_the_head_office_role(self):
        # 代表の clone で起きた試しの claude -p（名前が無い）や、窓口が動いている間に起きた会話は、窓口として振る舞わない（53d5d1・6be241）
        write(pathlib.Path(self.src) / ".claude" / "company.toml", '[[roles]]\nname = "段取り"\ninstructions = "頼みを配る。"\n')
        provision.mark(self.src, self.src, {"role": "段取り", "name": "段取り", "session": "s-desk", "pid": "999999999"}, self.g)

        def told(payload, running):
            out = io.StringIO()
            with mock.patch.object(claudex, "running", lambda pid: running), contextlib.redirect_stdout(out):
                role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "source": "startup", **payload})), self.env)
            return "頼みを配る。" in out.getvalue()
        self.assertTrue(told({"session_id": "s-desk"}, True))                                  # 窓口の会話
        self.assertFalse(told({"session_id": "s-probe"}, True))                                # 試しの claude -p
        self.assertFalse(told({"session_id": "s-two", "session_title": "段取り"}, True))       # 窓口が動いている間の 2 つ目
        self.assertTrue(told({"session_id": "s-next", "session_title": "段取り"}, False))      # 窓口を終えて起動し直した会話
        self.assertFalse(told({"session_id": "s-probe"}, False))                               # 名前の無い会話は席に座らない
        out = io.StringIO()
        with contextlib.redirect_stdout(out):   # 部署の worktree は今までどおり
            provision.mark(self.place, self.src, {"role": "段取り"}, self.g)
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "s-x", "source": "startup"})), self.env)
        self.assertIn("頼みを配る。", out.getvalue())

    def test_a_work_place_with_the_desk_attrs_copied_from_the_head_office_does_not_make_its_talk_the_desk(self):
        # git worktree add が本社の窓口の属性（--desk だけが書く company.pid を含む）を PR の作業場に写した。そこで起動した PR の会話が
        # 窓口の本文を受け、自分の居るブランチに部署を立てようとした（3d3ccc）。属性を書いた worktree の id を書く前の版の本社から写った
        # 物（id が無い）も写しと見る。処理の番号が使い回されて、そこで起きた会話が --desk の会話と同じ処理に見えても、席に座らない
        # （guided-resolver の本社でない worktree 2 か所に残っていた。my_notes の受付 20261019-210027-55dd62）
        write(pathlib.Path(self.src) / ".claude" / "company.toml", '[[roles]]\nname = "窓口"\ninstructions = "頼みを配る。"\n')
        self.g.enable_worktree_config(self.src)
        for k, v in (("role", "窓口"), ("name", "窓口"), ("session", "s-desk"), ("pid", str(os.getpid()))):
            self.g.set_worktree_attr(self.src, k, v)   # id を書く前の版の --desk（company.worktree-id を書かない）
        copy = os.path.join(os.path.realpath(tempfile.mkdtemp(prefix="works-dispatch-pr-")), "pr")
        self.addCleanup(shutil.rmtree, os.path.dirname(copy), True)
        self.g.add_detached(self.src, copy, "HEAD")
        self.assertEqual(self.g.worktree_attrs(copy, copies=True)["pid"], str(os.getpid()))   # git が写した
        self.assertEqual(self.g.worktree_attrs(copy), {})
        out = io.StringIO()
        with mock.patch.object(claudex, "running", lambda pid: True), contextlib.redirect_stdout(out):
            role_hook.main(io.StringIO(json.dumps({"cwd": copy, "session_id": "s-pr", "source": "startup"})), self.env)
            role_hook.main(io.StringIO(json.dumps({"cwd": copy, "session_id": "s-pr2", "source": "clear"})), self.env)
            self.assertIsNone(wake_hook.plan({"cwd": copy, "session_id": "s-pr2"}))   # 窓口あての頼みを待ち受けない
        self.assertNotIn("頼みを配る。", out.getvalue())
        self.assertEqual(self.g.worktree_attrs(copy, copies=True)["session"], "s-desk")   # PR の会話の /clear で席を取らない
        out = io.StringIO()
        with contextlib.redirect_stdout(out):   # 本社の窓口の会話は今までどおり
            role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-desk", "source": "startup"})), self.env)
        self.assertIn("頼みを配る。", out.getvalue())
        # 前の版で立てた部署に、本社から写った company.pid だけが残った物は、部署の属性を書いた id を持つので部署のまま読む
        provision.mark(self.place, self.src, {"role": "担当", "name": "直し", "session": "s-dept", "pid": "999999999"}, self.g)
        self.assertEqual(self.g.worktree_attrs(self.place)["name"], "直し")

    def test_running_reads_the_command_of_the_process(self):
        import subprocess
        def runner(out, rc=0):
            return lambda argv: subprocess.CompletedProcess(argv, rc, out, "")
        self.assertTrue(claudex.running("12", runner("/Users/x/.local/share/claude/versions/2.1.302 --name 段取り\n")))
        self.assertFalse(claudex.running("12", runner("/usr/bin/python3 x.py\n")))   # 番号が使い回された別の処理
        self.assertFalse(claudex.running("12", runner("", rc=1)))                     # もう居ない
        self.assertFalse(claudex.running(None, runner("claude")))

    def test_a_former_role_name_reads_as_the_current_role_and_is_rewritten(self):
        write(pathlib.Path(self.src) / ".claude" / "company.toml",
              'name = "co"\ndesk_role = "窓口"\n[[roles]]\nname = "段取り"\nformer_names = ["窓口"]\ninstructions = "頼みを配る。"\n')
        provision.mark(self.src, self.src, {"role": "窓口", "session": "s-desk"}, self.g)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-desk", "source": "startup"})), self.env)
        self.assertIn("役は「段取り」。\n頼みを配る。", json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.g.worktree_attrs(self.src)["role"], "段取り")
        shape = role.load("x", (pathlib.Path(self.src) / ".claude" / "company.toml").read_text(encoding="utf-8"))
        self.assertEqual((shape["desk_role"], role.current(shape, "窓口"), role.current(shape, "作業")), ("段取り", "段取り", "作業"))

    def test_a_running_talk_gets_the_new_role_text_once_on_its_next_prompt(self):
        shape = pathlib.Path(self.src) / ".claude" / "company.toml"
        write(shape, '[[roles]]\nname = "相談"\ninstructions = "持ち主と話す。"\n')
        provision.mark(self.place, self.src, {"role": "相談", "session": "s1"}, self.g)
        with contextlib.redirect_stdout(io.StringIO()):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "s1", "source": "startup"})), self.env)

        def prompt(sid="s1"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                role_hook.prompt(io.StringIO(json.dumps({"cwd": self.place, "session_id": sid})), self.env)
            return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"] if out.getvalue() else None
        self.assertIsNone(prompt())   # 会話の始まりに足した物のまま
        write(shape, '[[roles]]\nname = "相談"\ninstructions = "持ち主と話し、頼みは段取りに渡す。"\n')
        got = prompt()
        self.assertTrue(got.startswith(role_hook.CHANGED_HEAD), got)
        self.assertIn("頼みは段取りに渡す。", got)
        self.assertIsNone(prompt())   # 足すのは替わった後の 1 度だけ
        self.assertIsNone(prompt("s-other"))   # 場所の属性の会話でない会話には足さない

    def test_a_talk_outside_the_departments_of_a_company_gets_how_to_ask_other_companies(self):
        # 部署でない会話（PR のブランチの会話など）が SendMessage で頼み、受付の台帳に頼み元が残らなかった（2026-10-17 の guided-resolver）
        def started(cwd, sid):
            out = io.StringIO()
            with mock.patch.object(claudex, "running", lambda pid: True), contextlib.redirect_stdout(out):
                role_hook.main(io.StringIO(json.dumps({"cwd": cwd, "session_id": sid, "source": "startup"})), self.env)
            return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"] if out.getvalue() else None
        self.assertIsNone(started(self.place, "s-a"))   # 会社でないリポジトリには何も足さない
        write(pathlib.Path(self.src) / ".claude" / "company.toml", 'name = "co"\n' + SHAPE.replace('name = "試しの会社"\n', ""))
        got = started(self.place, "s-b")
        self.assertIn("会社「co」", got)
        self.assertIn(f"{role_hook.RUN} --ask <会社の名前> --text <頼み>", got)
        self.assertEqual(len(got.splitlines()), 1)   # 毎回の起動の量に入るので 1 行
        provision.mark(self.src, self.src, {"role": "調べ役", "name": "調べ", "session": "s-desk", "pid": "999999999"}, self.g)
        self.assertEqual(started(self.src, "s-c"), got)   # 本社の、窓口でない会話
        self.assertEqual(started(self.src, "s-desk"), role_hook.text_for(self.src, self.env))   # 窓口と部署は役の本文だけ（今までどおり）
        provision.mark(self.place, self.src, {"role": "調べ役"}, self.g)
        self.assertEqual(started(self.place, "s-d"), role_hook.text_for(self.place, self.env))

    def test_a_talk_running_before_the_repo_became_a_company_gets_the_hint_once_on_its_next_prompt(self):
        def prompt(sid="s1", cwd=None):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                role_hook.prompt(io.StringIO(json.dumps({"cwd": cwd or self.place, "session_id": sid})), self.env)
            return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"] if out.getvalue() else None
        with contextlib.redirect_stdout(io.StringIO()):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "s1", "source": "startup"})), self.env)
        self.assertIsNone(prompt())   # まだ会社でない
        conf = pathlib.Path(self.env["WORKS_DISPATCH_CONFIG"]).parent   # 会社の形を設定の置き場に書いて会社にした
        write(conf / "companies" / (urllib.parse.quote(os.path.realpath(self.src), safe="") + ".toml"), SHAPE)
        self.assertIn("会社「試しの会社」", prompt())
        self.assertIsNone(prompt())   # 足すのは 1 度だけ
        provision.mark(self.place, self.src, {"role": "調べ役", "session": "s2"}, self.g)
        self.assertIsNone(prompt("s9"))   # 部署の場所のほかの会話には、役の本文を足した会話と同じく足さない
        provision.mark(self.src, self.src, {"role": "調べ役", "name": "調べ", "session": "s-desk", "pid": "999999999"}, self.g)
        with mock.patch.object(claudex, "running", lambda pid: True):
            self.assertIn("会社「試しの会社」", prompt("s-head", self.src))   # 本社の、窓口でない会話
            got = prompt("s-desk", self.src)   # 窓口の会話には、頼み方でなく役の本文（changed。控えが無いので今足す）
            self.assertTrue(got.startswith(role_hook.CHANGED_HEAD) and "SendMessage" not in got, got)

    def test_plugin_declares_the_prompt_hook_in_sync(self):
        hooks = json.loads((pathlib.Path(DISPATCH).parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        [h] = [h for grp in hooks["UserPromptSubmit"] for h in grp["hooks"] if "role_hook.py" in h["command"]]
        self.assertTrue(h["command"].endswith('role_hook.py" --prompt'))
        self.assertFalse(h.get("async"))   # 裏で走るフックの返す文は会話に入らない

    def test_plugin_declares_the_hook_on_the_existing_script(self):
        hooks = json.loads((pathlib.Path(DISPATCH).parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        [command] = [h["command"] for grp in hooks["SessionStart"] for h in grp["hooks"] if not h.get("asyncRewake")]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/dispatch/role_hook.py", command)
        self.assertTrue((pathlib.Path(DISPATCH) / "role_hook.py").is_file())


BG = re.compile(r"^(claude-a\d) --bg --name ")


class TaskWithRole(unittest.TestCase):
    """入口の --task が、会社の形の役の項目から --settings・--model・GH_TOKEN を渡す。場の作りは --task の試験のものを借りる
    （継ぐと、その試験が二度走る）。"""

    setUp, run_task, place = test_task.Task.setUp, test_task.Task.run_task, test_task.Task.place

    def ports(self, sessions=None, starts=True, name="直し"):
        ports = test_task.Task.ports(self, sessions, starts)
        d = pathlib.Path(self.cfg).parent
        dirs = {"claude-a1": f"{d}/c1"}

        def listed(cdir, include_done=False):
            got = []
            for i, w in enumerate(x for x in ports.term.writes if x[0] == "run" and BG.search(x[2])):
                if dirs[BG.search(w[2]).group(1)] == cdir:
                    cwd = next(p["cwd"] for p in ports.term.panes() if p["pane_id"] == w[1])
                    got.append({"id": f"bg{i}", "sessionId": f"bg{i}-full", "name": name, "cwd": cwd, "kind": "background",
                                "state": "working", "startedAt": i})
            return got

        ports.list_sessions = listed
        return ports

    def shape(self, text=SHAPE):
        write(pathlib.Path(gitx_source(self.cfg)) / ".claude" / "company.toml", text)

    def test_reused_place_drops_the_attrs_of_the_previous_run(self):
        src = gitx_source(self.cfg)
        place = str(pathlib.Path(self.root) / "reused")
        self.g.add_worktree(place, "task/fix", "origin/main")
        provision.mark(place, src, {"gh-user": "old", "config": "old.toml", "boss": "old-boss"}, self.g)
        rc, out = self.run_task(self.ports())   # 会社の形も gh_user も無い回
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(place)
        self.assertNotIn("gh-user", attrs)
        self.assertNotIn("boss", attrs)
        self.assertEqual(attrs["config"], self.cfg)

    def test_role_model_is_read_from_the_default_branch_when_the_head_office_is_on_an_old_branch(self):
        src = gitx_source(self.cfg)
        self.g.push_origin("main", {".claude/company.toml": SHAPE}, "company")   # 会社の形はメインブランチに在る
        self.g.fetch(src, "main")
        write(pathlib.Path(src) / ".claude" / "company.toml", 'name = "古い形"\n')   # 元の clone の作業ツリーは古い（役が無い）
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.term.writes if w[0] == "run" and BG.search(w[2])]
        self.assertIn("haiku", command)

    def test_role_settings_model_and_gh_user_reach_the_department(self):
        self.shape()
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.term.writes if w[0] == "run" and BG.search(w[2])]
        path = self.place(ports)
        settings = os.path.join(self.g.git_dir(path), role.SETTINGS_FILE)
        self.assertEqual(json.loads(pathlib.Path(settings).read_text(encoding="utf-8"))["worktree"], {"bgIsolation": "none"})
        if os.name != "nt":
            self.assertEqual(shlex.split(command)[:10], ["claude-a1", "--bg", "--name", "直し", "--settings", settings, "--model", "haiku",
                                                         "--effort", "low"])
        self.assertNotIn("GH_TOKEN", command)
        # gh のアカウントは名前だけを部署の属性に書く（鍵はフックが会話の Bash に入れる）。既定の設定の置き場でないので、その場所も
        attrs = self.g.worktree_attrs(path)
        self.assertEqual((attrs["gh-user"], attrs["config"]), ("gh-co", self.cfg))
        self.assertIn("started", out)
        # 設定のファイルは部署の .git の場所に在り、作業場の git status に出ない
        self.assertEqual(self.g.is_clean(path), True)

    def test_users_own_gh_user_comes_before_the_company_one(self):
        self.shape()
        p = pathlib.Path(self.cfg)
        p.write_text(p.read_text(encoding="utf-8") + 'gh_user = "me"\n', encoding="utf-8")
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "出荷役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.term.writes if w[0] == "run" and BG.search(w[2])]
        if os.name != "nt":
            # 役に設定が無ければ、いつもの部署の設定のファイル
            self.assertEqual(shlex.split(command)[5], ports.department_settings())
        self.assertNotIn("--model", command)
        self.assertNotIn("--effort", command)
        self.assertEqual(self.g.worktree_attrs(self.place(ports))["gh-user"], "me")
        self.assertIn("gh-co", out)

    def test_duty_model_and_effort_come_before_the_roles(self):
        # 部署の名前（--task）と同じ name の受け持ちに書いた値が、役の値より先に効く。ほかの名前の部署は役の値のまま
        self.shape(SHAPE + '\n[[skills]]\nname = "直し"\nrole = "調べ役"\nmodel = "sonnet"\neffort = "high"\n')
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("モデル sonnet、effort high", out)
        rc, out = self.run_task(ports, "--role", "調べ役", "--dry-run", name="別の直し")
        self.assertEqual(rc, 0, out)
        self.assertIn("モデル haiku、effort low", out)
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.term.writes if w[0] == "run" and BG.search(w[2])]
        self.assertRegex(command, r'--model "?sonnet\b.*--effort "?high\b')

    def test_duty_settings_reach_its_standing_and_one_off_departments_and_no_other(self):
        # 受け持ちの settings は、その受け持ちの名前の部署と「<受け持ち>：<何をするか>」の部署の --settings に、役の設定の上から入る。
        # 同じ役のほかの名前の部署には入らない
        self.shape(SHAPE + '\n[[skills]]\nname = "調べもの"\nsettings = { promptCacheTtl = "5m" }\n')
        got = {}
        for name, branch in (("調べもの", "task/a"), ("調べもの：原典の確かめ", "task/b"), ("直し", "task/c")):
            ports = self.ports(name=name)
            rc, out = self.run_task(ports, "--role", "調べ役", name=name, branch=branch)
            self.assertEqual(rc, 0, out)
            [command] = [w[2] for w in ports.term.writes if w[0] == "run" and BG.search(w[2])]
            path = os.path.join(self.g.git_dir(self.place(ports, branch)), role.SETTINGS_FILE)
            self.assertIn(path, command)
            got[name] = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        for name in ("調べもの", "調べもの：原典の確かめ"):
            self.assertEqual(got[name]["promptCacheTtl"], "5m", name)
            self.assertEqual(got[name]["permissions"], {"deny": ["Artifact", "Workflow"]}, name)   # 役の設定も残る
        self.assertNotIn("promptCacheTtl", got["直し"])
        rc, out = self.run_task(self.ports(), "--role", "調べ役", "--dry-run", name="調べもの：下調べ", branch="task/d")
        self.assertEqual(rc, 0, out)
        self.assertIn("worktree, promptCacheTtl（受け持ち 調べもの の settings を重ねた）", out)

    def test_bad_duty_effort_is_said_at_launch_and_the_role_value_is_used(self):
        self.shape(SHAPE + '\n[[skills]]\nname = "直し"\neffort = "hihg"\n')
        rc, out = self.run_task(self.ports(), "--role", "調べ役", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("外して、役の effort で起動する", out)
        self.assertIn("モデル haiku、effort low", out)

    def test_effort_inherit_takes_the_callers_effort(self):
        self.shape(SHAPE.replace('effort = "low"', 'effort = "inherit"'))
        ports = self.ports()
        ports.env = {**ports.env, "CLAUDE_EFFORT": "xhigh"}
        rc, out = self.run_task(ports, "--role", "調べ役", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("モデル haiku、effort xhigh", out)
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.term.writes if w[0] == "run" and BG.search(w[2])]
        self.assertRegex(command, r'--effort "?xhigh\b')

    def test_effort_inherit_without_the_callers_effort_starts_at_the_default_and_says_so(self):
        self.shape(SHAPE.replace('effort = "low"', 'effort = "inherit"'))
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.term.writes if w[0] == "run" and BG.search(w[2])]
        self.assertNotIn("--effort", command)
        self.assertIn("CLAUDE_EFFORT が無い", out)

    def test_unknown_explicit_role_stops_before_anything(self):
        self.shape()
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べやく")
        self.assertEqual(rc, 2)
        self.assertIn("在る役: 調べ役, 出荷役", out)
        self.assertEqual(ports.term.writes, [])

    def test_dry_run_shows_the_role_settings_and_the_gh_account(self):
        self.shape()
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("モデル haiku、effort low、--settings の鍵 enabledPlugins, permissions, worktree", out)
        self.assertIn("gh のアカウント: gh-co（会話の Bash がコマンドごとに鍵を取り出し", out)
        self.assertEqual(ports.term.writes, [])
