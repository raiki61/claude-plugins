"""graphloops が子の claude に頼る外の形を、実物から採った見本（cli/。採り方は cli/versions.json）と突き合わせる契約の試験。
claude は起動しない——手元の claude との突き合わせは cli_contract.py --live（費用なし）で、claude を上げたら --capture で見本を採り直す。

見ること: graph と engine が渡す旗が claude --help に在る・決まった値が選択肢に在る（載らない値は起動の確かめで受け付けられた）・
--settings に渡すキーが設定の JSON Schema に在る・本物の包みに engine が読むフィールドが型どおり在る・欠けたら黙って 0 にせず数えて出す。"""
import json

import cli_contract as cc
import pytest

from engine import intake, role_run

HELP = cc.HELP.read_text(encoding="utf-8")
META = json.loads(cc.VERSIONS.read_text(encoding="utf-8"))
SAMPLES = {"success": json.loads(cc.SUCCESS.read_text(encoding="utf-8")),
           "not-logged-in": json.loads(cc.PROBE.read_text(encoding="utf-8"))}
# engine が読むフィールドの型（role_run.unwrap・session_costs・commands の permission_denials の数え）
TYPES = {"type": str, "session_id": str, "subtype": str, "is_error": bool, "total_cost_usd": (int, float), "permission_denials": list,
         "num_turns": int, "duration_ms": int, "duration_api_ms": int, "usage": dict, "result": str}


def test_the_samples_name_the_claude_they_came_from():
    for part in ("success", "help", "probe"):
        assert META[part]["claude"] and META[part]["captured"] and META[part]["how"], part


# ---------------------------------------------------------------- 旗と値
def test_every_flag_graphloops_passes_is_in_the_captured_help():
    defined, mentioned = cc.help_flags(HELP)
    assert cc.used_flags() - defined - mentioned == set()
    # 段を持たずに名乗るだけの旗は、起動の確かめで受け付けられたこと（help の書き方が変わると段から消えうる）
    probed = {a for argv in META["probe"]["argvs"] for a in argv}
    assert (cc.used_flags() & mentioned) <= probed


def test_every_fixed_value_is_a_listed_choice_or_was_accepted_by_the_probe():
    assert cc.unlisted_values(HELP) == []
    probed = META["probe"]["argvs"]
    for flag, hidden in cc.HIDDEN_VALUES.items():
        for v in hidden:
            assert any(flag in a and a[a.index(flag) + 1] == v for a in probed), (flag, v)


def test_the_probe_covered_every_flag_and_every_permission_mode():
    probed = META["probe"]["argvs"]
    assert cc.used_flags() - {"--resume"} <= {a for argv in probed for a in argv}
    modes = {a[a.index("--permission-mode") + 1] for a in probed if "--permission-mode" in a}
    assert cc.used_values()["--permission-mode"] <= modes


def test_the_help_reader_does_not_pass_vacuously():
    """読み方が空振りしていない——段を消した旗・選択肢から消した値・名乗るだけの形を外した旗は、見本の上で拾われなくなる"""
    defined, mentioned = cc.help_flags(HELP)
    assert {"-p", "--print", "--allowedTools", "--allowed-tools", "--permission-prompts"} <= defined
    assert "--append-system-prompt-file" in mentioned
    cut = "\n".join(line for line in HELP.splitlines() if not line.lstrip().startswith("--permission-prompts"))
    assert "--permission-prompts" not in cc.help_flags(cut)[0]
    assert "--append-system-prompt-file" not in cc.help_flags(HELP.replace("--append-system-prompt[-file]", "x"))[1]
    assert cc.help_choices(HELP, "--effort") == ["low", "medium", "high", "xhigh", "max"]
    assert "none" not in (cc.help_choices(HELP.replace('"host", "none"', '"host"'), "--permission-prompts") or [])
    assert ("--output-format", "json", ["text", "stream-json"]) in cc.unlisted_values(HELP.replace('"json",', ""))


# ---------------------------------------------------------------- 設定のキー
def test_every_settings_key_engine_writes_is_in_the_settings_schema():
    schema = json.loads(cc.SCHEMA.read_text(encoding="utf-8"))["keys"]
    for name, settings in cc.used_settings():
        assert cc.dotted(settings) - set(schema) == set(), name


def test_settings_key_reader_does_not_pass_vacuously():
    keys = cc.dotted({"sandbox": {"enabled": True, "network": {"allowedDomains": []}, "filesystem": {}}})
    assert keys == {"sandbox.enabled", "sandbox.network.allowedDomains", "sandbox.filesystem"}


# ---------------------------------------------------------------- 包みのフィールド
@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_real_envelopes_carry_every_field_engine_reads(name):
    env = SAMPLES[name]
    for k in set(role_run.ENVELOPE_READS) | set(TYPES):
        assert isinstance(env.get(k), TYPES.get(k, object)) and not (TYPES.get(k) is int and isinstance(env[k], bool)), (name, k)
    assert env["type"] == "result"
    assert set(role_run.SUMMARY_KEYS) <= set(env)


def test_unwrap_reads_the_real_envelopes():
    text, summary, bad = role_run.unwrap(json.dumps(SAMPLES["success"]).encode("utf-8"))
    assert (text, bad) == ("OK", None) and "missing" not in summary and summary["total_cost_usd"] > 0
    text, summary, bad = role_run.unwrap(json.dumps(SAMPLES["not-logged-in"]).encode("utf-8"))
    # is_error が真で subtype が success の形（実物）——subtype だけを見ると成功に数える
    assert text is None and "Not logged in" in bad and "missing" not in summary


@pytest.mark.parametrize("field", role_run.ENVELOPE_READS)
def test_a_lost_field_is_named_in_the_summary(field):
    env = {k: v for k, v in SAMPLES["success"].items() if k != field}
    _, summary, _ = role_run.unwrap(json.dumps(env).encode("utf-8"))
    assert summary["missing"] == [field]


def test_lost_cost_is_counted_in_the_report_not_summed_as_zero(tmp_path):
    """包みから total_cost_usd が消えた（または数でなくなった）行は、status・run の報告の cost_usd.unknown に数える"""
    rows = []
    for env in ({k: v for k, v in SAMPLES["success"].items() if k != "total_cost_usd"}, {**SAMPLES["success"], "total_cost_usd": None},
                SAMPLES["success"]):
        _, summary, _ = role_run.unwrap(json.dumps(env).encode("utf-8"))
        rows.append({"op": "role_run", "node": "p1.x", "turn": 1, **summary})
    rows.append({"op": "role_run", "node": "p1.y", "envelope": True, "session_id": "old", "subtype": "success", "is_error": False})  # missing を書く前の版の行
    rows.append({"op": "role_run", "node": "p1.z", "envelope": False})                                   # 包みでない回は数えない
    (tmp_path / "trace.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = role_run.trace_costs(tmp_path / "trace.jsonl")
    assert got["unknown"]["fields"] == {"total_cost_usd": 3}
    assert "claude --version" in got["unknown"]["why"] and intake.CLAUDE_CHECK in got["unknown"]["why"]
    assert got["usd"] == round(SAMPLES["success"]["total_cost_usd"], 4)


def test_the_notices_point_at_a_readme_section_that_names_the_live_check():
    """知らせの文（init の claude の版のずれ・費用の包みの欠け）は手順を写さず README の見出しを指す——指す見出しが在り、そのセクションが
    --live の打ち方を書いている（見出しを改めると知らせが空を指す）"""
    text = (cc.PLUGIN / "README.md").read_text(encoding="utf-8")
    head = f"\n## {intake.CLAUDE_CHECK}\n"
    assert head in text
    assert "python3 graphloops/tests/py/cli_contract.py --live" in text.split(head, 1)[1].split("\n## ", 1)[0]


def test_no_unknown_when_every_envelope_is_whole(tmp_path):
    _, summary, _ = role_run.unwrap(json.dumps(SAMPLES["success"]).encode("utf-8"))
    (tmp_path / "trace.jsonl").write_text(json.dumps({"op": "role_run", "node": "p1.x", **summary}) + "\n", encoding="utf-8")
    assert "unknown" not in role_run.trace_costs(tmp_path / "trace.jsonl")


def test_live_probe_judges_rejections_and_lost_fields():
    """起動の確かめの合否の読み方（--live・--capture が使う）——見本の包みは通り、拒まれた旗・読めない設定・欠けたフィールドは落ちる"""
    ok = json.dumps(SAMPLES["not-logged-in"])
    assert cc.check_probe([], 1, ok, "") is None
    assert "旗か値を拒んだ" in cc.check_probe([], 1, "", "error: unknown option '--effort'")
    assert "--settings を読まなかった" in cc.check_probe([], 1, ok, "These settings files did not load")
    lost = json.dumps({k: v for k, v in SAMPLES["not-logged-in"].items() if k != "total_cost_usd"})
    assert "total_cost_usd" in cc.check_probe([], 1, lost, "")
