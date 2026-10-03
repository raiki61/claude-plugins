"""pack の YAML の決まり（設計書 7 節の守りと期限・Ruling R4）の検査。

check_file(path) は 1 本の工程の YAML を読み、決まりに反する所を文の一覧で返す（空なら緑）。決まり:
- bash・script の節は timeout: 1728000000（20 日）を持つ。2^31-1 ms を超える値は Archon の検査を通るのに実行で即失敗する
- AI の節（prompt: か command: を持つ節）は idle_timeout: 1728000000・output_format・
  sandbox: {enabled: true, allowUnsandboxedCommands: false} を持つ（Ruling R12。Bash がサンドボックスの外へ出る道を閉じる）
- AI の節の allowed_tools は [Read, Grep, Glob] の部分集合（無ければ全部の道具を持つので違反）。sandbox は狭める鍵
  （NARROW_SANDBOX_KEYS: enabled・allowUnsandboxedCommands・failIfUnavailable）だけを持つ。
  外れてよいのは表 EXCEPTIONS の節だけ（どの節が・どの道具と・どの sandbox の形を持ってよいかを 1 つの表に置く）:
  - blk-fix/blk-fix.yaml の節 fix（書く役）・fix-ruled（食い違いの裁定の後の 2 回目の修正役）: 道具の決まりの外
  - blk-spec/blk-spec.yaml の節 spec-write・spec-revise（仕様の道の writer。受け入れ条件のテストを対象に書く）: 道具の決まりの外
  - blk-ci/blk-ci.yaml の節 ci（CI の任せ先の役。裁定 R52・R56）: 読む道具に Bash と web（テストを走らせる。Edit・Write は持たない）。
    sandbox は graphloops の任せ先（role_run.delegate_settings）と同じ広い形（allowWrite ['/']・網）そのもので、本物の作業ツリーは
    包みが守るので、output_format の印に旗 no-tree-write を持つ
  - blk-material/blk-material.yaml の Bash を持つ役（素材集め。本線 R3）: graphloops の起こし方と同じ道具（investigator・任せ先は
    Read・Grep・Glob・Bash・WebSearch・WebFetch、局所レビューはそれに Skill・Agent）。任せ先（graph の delegate を持つ 4 節）の
    sandbox は DELEGATE_SANDBOX、investigator と局所レビューは網を閉じて読むだけの口 works-gh だけを sandbox の外に出す
    MATERIAL_SANDBOX。どれも印に旗
    no-tree-write（本物の作業ツリーは包みが守る）。局所レビューも settingSources は [user]（下の決まり。pr-review-toolkit の agent のレンズは
    利用者が入れた物（許す一覧 borrow.json）から dev/toolset.py が隔離した設定に入れる）
  - 読む道具に web（WebSearch・WebFetch）を足す節（WEB_READERS。本線の run_by が judge か、読むだけの writer か、全部の道具を
    持つ定義を読むだけに狭めた目。書く道具と shell は持たない。tests/test_tool_parity.py が本線の道具以上かを見る）:
    blk-eyes の r1-minimality・premise-check・r1-comments、blk-judge の judge、blk-plan の plan・plan-revise・plan-review、blk-rejudge の
    rejudge・rejudge-third、blk-purpose の purpose、blk-report の report-items・report-write、blk-spec の spec-review
  - blk-premises/blk-premises.yaml の節 premises（測る役）: 読む道具に Bash と web（測るためにコマンドを走らせるが書く道具は
    持たない。Bash は狭い sandbox の中。作業ツリーを変えれば受け付けが写しと比べて拒む）
- 書く役でなく Bash・Edit・Write（TREE_CHANGERS）も持たない AI の節は節の段の mutates_checkout: false を持ち、それ以外の AI の節は
  持たない（設計書 7 節の読むだけの役）。Bash を持つ読む役は、受け付けの出し直しで自分の残し物を片付けて通る道を残す。
  false の節では Archon が節の前のやり直し用の checkpoint を作らないが、作業ツリーを変える道具が無いので巻き戻す物も、
  resume の時に基準へ残る前の試みの汚れも無い
- AI の節は settingSources: [user] を持つ（P1 計画 Task 20・裁定 P1-R8）。役は開発の殻が隔離した CLAUDE_CONFIG_DIR だけを読み、
  そこには許す一覧（.shared/borrow/borrow.json）の物しか無い（dev/toolset.py が組み、柵が一覧の外を拒む）。対象の CLAUDE.md
  （project）は読ませない。書かなければ Archon は ['project', 'user'] を読ませ、CLAUDE.md の文体の決まりが JSON だけを返す約束を崩す。
  skills: は書いてもよく、書くなら名前の空でない一覧で、全部が borrow.json の superpowers.skills（SP_SKILLS）に在る
  （外れは表 SKILLS_EXTRA の節だけ: blk-material の local-review は Claude Code に同梱の code-review・simplify・security-review も書ける）
- approval・include・loop_group の節は期限を持たない。書く期限の欄は上の 2 つだけ（AI の節の timeout・bash の節の idle_timeout も違反）
- loop_group は max_iterations: 3 と until_bash を持つ。中の節（loop_group.nodes）も同じ決まりで辿る。
  3 でない上限は表 LOOP_MAX の輪だけ（blk-fix の TDD の輪: 単位の数が run ごとに違う。抜けるのは until_bash の印で、
  上限に届く周で機械が印を立てる。R50）
- loop_group の本体（入れ子の輪も）に approval の節を置かない（Archon #3532: 本体が関所で終わる輪の再開は止まった回の会話を
  引き継がない。関所は輪の外の最上段に置き、答えは with の from で後ろの節へ渡す）
- 上のどれでもない種類の節（loop: など）は違反（決まりを決めていない種類を黙って通さない）

違反の見本は tests/yaml_bad/（1 本 1 違反。どの決まりに引っかかるべきかは BAD_EXPECT に置き、件数だけでなく文面で照合する）、
守った見本は tests/yaml_good/。YAML を読むのはテストだけ（PyYAML は run.sh が足す）。
"""
import json
import pathlib
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent

DEADLINE = 1728000000                     # 20 日（ms）
READ_ONLY_TOOLS = {"Read", "Grep", "Glob"}
TREE_CHANGERS = {"Bash", "Edit", "Write"}   # 作業ツリーを変えうる道具（持つ節は mutates_checkout: false を書かない）
WRITER = ("blk-fix", "blk-fix.yaml", "fix")   # 書く道具を持ってよい節: (フォルダ, ファイル, 節)
TDD_WRITER = ("blk-fix", "blk-fix.yaml", "tdd")   # TDD の輪の修正役（テストを書く・直す・整える。設計 4 節）
RULED_WRITER = ("blk-fix", "blk-fix.yaml", "fix-ruled")   # 食い違いの裁定の後の 2 回目の修正役（修正役の会話の続き。印 continue=fix）
# max_iterations が 3 でない輪: (フォルダ, ファイル, 輪の節) → 上限（blk-fix/lib/tddloop.py の MAX_ITERATIONS と同じ値）
LOOP_MAX = {("blk-fix", "blk-fix.yaml", "tdd-loop"): 40}
CI_ROLE = ("blk-ci", "blk-ci.yaml", "ci")      # CI の任せ先の役（裁定 R52・R56）
MEASURER = ("blk-premises", "blk-premises.yaml", "premises")   # 前提の実測の役（読む道具に Bash だけを足す）
MEASURE_TOOLS = READ_ONLY_TOOLS | {"Bash", "WebSearch", "WebFetch"}
SPEC_WRITE = ("blk-spec", "blk-spec.yaml", "spec-write")     # 仕様の道の writer（本線 R2。受け入れ条件のテストを書く）
SPEC_REVISE = ("blk-spec", "blk-spec.yaml", "spec-revise")   # 同じ writer が審査の穴に答えて直す
REFIX_WRITERS = (("blk-refix", "blk-refix.yaml", "refix"), ("blk-refix", "blk-refix.yaml", "refix2"))   # 差分の審査の後の手直し（〔線A計〕T17）
REVIEW2 = ("blk-refix", "blk-refix.yaml", "review2")   # 手直しの差分の 2 回目の審査役（読むだけ）
PR_CHECK = ("blk-pr", "blk-pr.yaml", "pr-check")        # 並行 PR の任せ先（読むだけ＋Bash。gh は包みの読む口だけ。印の旗 no-post）
NARROW_SANDBOX_KEYS = {"enabled", "allowUnsandboxedCommands", "failIfUnavailable"}   # 狭める鍵（書き込み・網を広げない）
# graphloops の任せ先の sandbox（写しの engine の role_run.delegate_settings）から、起動ごとの denyWrite（包みが足す）と
# autoAllowBashIfSandboxed（Archon は bypassPermissions で起こすので要らない）を除いた形。tests/test_blk_ci.py が写しの関数と突き合わせる
DELEGATE_SANDBOX = {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
                    "enableWeakerNetworkIsolation": True,
                    "network": {"allowedDomains": ["*"], "allowLocalBinding": True},
                    "filesystem": {"allowWrite": ["/"]}}
# 決まりの外れの表: (フォルダ, ファイル, 節) → tools（持ってよい道具。None は道具の決まりの外）・sandbox（その形そのもの。
# 無ければ狭い形）・flag（印に要る旗）。外れを足す時は行を 1 つ足す（ほかの行と決まりの式は変えない）
# 素材集めの investigator と局所レビューの sandbox（graphloops の investigator の SANDBOX_BASE と同じ考え）: 網は閉じ（allowedDomains []。
# Archon が捨てる strictAllowlist は包みが足す）、読むだけの口 works-gh だけを sandbox の外で走らせる（excludedCommands。書く gh は
# 口の許す物の一覧と包みの旗 no-post の permissions.deny が止める）。GitHub の宛先を許すと、sandbox の中のコードが読むだけの口を
# 迂回して書ける（graphloops の role_run の注記）
MATERIAL_SANDBOX = {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
                    "excludedCommands": ["works-gh:*"], "network": {"allowedDomains": []}}
_MAT_TOOLS = READ_ONLY_TOOLS | {"Bash", "WebSearch", "WebFetch"}
_MATERIAL = {
    **{n: {"tools": _MAT_TOOLS, "sandbox": DELEGATE_SANDBOX, "flag": "no-tree-write"}
       for n in ("gate-efficacy", "test-double-fidelity", "main-path-observation", "provenance")},
    **{n: {"tools": _MAT_TOOLS, "sandbox": MATERIAL_SANDBOX, "flag": "no-tree-write"}
       for n in ("prior-decisions", "external-standards", "procedure-trace")},
    "local-review": {"tools": _MAT_TOOLS | {"Skill", "Agent"}, "sandbox": MATERIAL_SANDBOX, "flag": "no-tree-write"},
}
JUDGE_WEB_TOOLS = READ_ONLY_TOOLS | {"WebSearch", "WebFetch"}   # graphloops の judge の定義（agents/judge.md）の道具
# 読む道具に web だけを足す節（本線の judge・読むだけの writer・読むだけに狭めた comment-analyzer。持ち主 2026-09-28）
WEB_READERS = (("blk-fix", "blk-fix.yaml", "rule"),   # 食い違いの裁定役（読むだけ。本線の judge に当たる）
               ("blk-eyes", "blk-eyes.yaml", "r1-minimality"), ("blk-eyes", "blk-eyes.yaml", "premise-check"),
               ("blk-eyes", "blk-eyes.yaml", "r1-comments"), ("blk-judge", "blk-judge.yaml", "judge"),
               ("blk-plan", "blk-plan.yaml", "plan"), ("blk-plan", "blk-plan.yaml", "plan-review"),
               ("blk-plan", "blk-plan.yaml", "plan-revise"),   # 事前審査の壁打ちの直しの役（修正案の役の会話の続き。読むだけ）
               ("blk-rejudge", "blk-rejudge.yaml", "rejudge"), ("blk-rejudge", "blk-rejudge.yaml", "rejudge-third"),
               ("blk-purpose", "blk-purpose.yaml", "purpose"), ("blk-report", "blk-report.yaml", "report-items"),
               ("blk-report", "blk-report.yaml", "report-write"), ("blk-spec", "blk-spec.yaml", "spec-review"))
EXCEPTIONS = {
    WRITER: {"tools": None},
    SPEC_WRITE: {"tools": None},
    SPEC_REVISE: {"tools": None},
    TDD_WRITER: {"tools": None},
    RULED_WRITER: {"tools": None},
    CI_ROLE: {"tools": MEASURE_TOOLS, "sandbox": DELEGATE_SANDBOX, "flag": "no-tree-write"},
    **{("blk-material", "blk-material.yaml", n): row for n, row in _MATERIAL.items()},
    **{w: {"tools": JUDGE_WEB_TOOLS} for w in WEB_READERS},
    MEASURER: {"tools": MEASURE_TOOLS},
    **{w: {"tools": None} for w in REFIX_WRITERS},
    PR_CHECK: {"tools": MEASURE_TOOLS, "sandbox": MATERIAL_SANDBOX, "flag": "no-post"},
}
# skills: に書いてよいスキル: 許す一覧の superpowers のスキル（dev/toolset.py が隔離した設定の skills/ に写す物と同じ一覧）
SP_SKILLS = frozenset(json.loads((ROOT / ".shared" / "borrow" / "borrow.json").read_text(encoding="utf-8"))
                      ["superpowers"]["skills"])
# skills: の外れの表: (フォルダ, ファイル, 節) → SP_SKILLS のほかに書いてよいスキル。Claude Code に同梱のスキルは隔離した設定の
# 置き場から読む物ではないので、隔離を崩さない。素材集めの局所レビューのレンズ（material.SKILLS）だけ
BUNDLED_SKILLS = frozenset({"code-review", "simplify", "security-review"})
SKILLS_EXTRA = {("blk-material", "blk-material.yaml", "local-review"): BUNDLED_SKILLS}
AI_KEYS = ("prompt", "command")
TIMED_KEYS = ("bash", "script")
QUIET_KEYS = ("approval", "include", "loop_group")   # 期限を持たない種類
# 役の節: (フォルダ, ファイル, 節)。どれもブロックの最初の AI の節で、輪（loop_group）の 1 周目の新しい会話で起きる
ROLES = (("blk-judge", "blk-judge.yaml", "judge"), ("blk-fix", "blk-fix.yaml", "fix"), TDD_WRITER,
         ("blk-delta", "blk-delta.yaml", "review"), ("blk-purpose", "blk-purpose.yaml", "purpose"), CI_ROLE, MEASURER,
         SPEC_WRITE, *REFIX_WRITERS, REVIEW2, PR_CHECK, ("blk-plan", "blk-plan.yaml", "plan"),
         ("blk-plan", "blk-plan.yaml", "plan-review"))


# 違反の見本（yaml_bad の stem）→ 出るべき違反の文面の一部。狙いの検査が壊れて別の検査が偶然 1 件出しても赤になるように、
# 節と決まりと実際の値まで書く（ESLint の RuleTester が invalid な例ごとに messageId を求めるのと同じ考え）
BAD_EXPECT = {
    "ai_no_idle_timeout": "節 judge: AI の節の idle_timeout が 1728000000 でない（None）",
    "ai_no_output_format": "節 judge: AI の節に output_format が無い",
    "ai_no_sandbox": "節 judge: AI の節の sandbox が {enabled: true, allowUnsandboxedCommands: false} でない"
                     "（{'enabled': False, ",
    "ai_no_setting_sources": "節 judge: AI の節の settingSources が [user] でない（'（無し）'",
    "ai_empty_setting_sources": "節 judge: AI の節の settingSources が [user] でない（[]",
    "user_skills_not_pinned": "節 judge: AI の節の skills: が借りたスキルの一覧の外を持つ（['brainstorming']",
    "ai_sandbox_unsandboxed_allowed": "節 judge: AI の節の sandbox が {enabled: true, allowUnsandboxedCommands: false} でない"
                                      "（{'enabled': True}）",
    "approval_with_timeout": "節 gate: approval の節に期限（timeout・idle_timeout）を書いた",
    "bash_outside_blk_ci": "節 ci: AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash']）",
    "fix_outside_blk_fix": "節 fix: AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash', 'Edit', 'Write']）",
    "measure_outside_blk_premises": "節 premises: AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash']）",
    "approval_in_loop": "節 judge-loop の中の節 gate: loop_group の本体に approval の節を置いた（関所の後の再開で輪の会話が欠ける",
    "loop_body_timeout": "節 judge-loop の中の節 accept: bash の節の timeout が 1728000000 でない（120000）",
    "loop_no_max": "節 judge-loop: loop_group の max_iterations が 3 でない（None）",
    "loop_no_until_bash": "節 judge-loop: loop_group に until_bash が無い",
    "readonly_no_allowed_tools": "節 judge: AI の節に allowed_tools が無い",
    "readonly_with_edit": "節 judge: AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Edit']）",
    "script_no_timeout": "節 accept: script の節の timeout が 1728000000 でない（None）",
    "timeout_25days": "節 run: bash の節の timeout が 1728000000 でない（2160000000）",
    "wide_sandbox_outside_blk_ci": "節 judge: AI の節の sandbox が広げる鍵を持つ"
                                   "（['enableWeakerNetworkIsolation', 'filesystem', 'network']。",
}


def _is_deadline(v):
    return type(v) is int and v == DEADLINE      # True や "1728000000" は通さない


def _kind(node):
    for k in AI_KEYS + TIMED_KEYS + QUIET_KEYS:
        if k in node:
            return k
    return None


def _allowed_tools(place, nid):
    """(フォルダ, ファイル) の節 nid が持ってよい道具の集合。None は決まりの外（書く役）"""
    return EXCEPTIONS.get((*place, nid), {}).get("tools", READ_ONLY_TOOLS)


def _check_sandbox(sb, node, at, row, out):
    """sandbox の形: 表の行が形を持てばその形そのもの（と印の旗）、無ければ狭める鍵だけ"""
    want = row.get("sandbox")
    if want is None:
        extra = sorted(set(sb) - NARROW_SANDBOX_KEYS) if isinstance(sb, dict) else []
        if extra:
            out.append(f"{at}: AI の節の sandbox が広げる鍵を持つ（{extra}。広い sandbox は表 EXCEPTIONS の節だけ）")
        return
    if sb != want:
        out.append(f"{at}: AI の節の sandbox が表の形でない（{sb!r}。表は {want!r}）")
    desc = (node.get("output_format") or {}).get("description") if isinstance(node.get("output_format"), dict) else None
    words = desc.split(" ") if isinstance(desc, str) and desc.startswith("works-node: ") else []
    if row["flag"] not in words[2:]:
        out.append(f"{at}: 広い sandbox の節の印に旗 {row['flag']} が無い（{desc!r}。包みが本物の作業ツリーを守れない）")


def _check_node(node, where, place, out):
    if not isinstance(node, dict):
        out.append(f"{where}: 節が表（mapping）でない")
        return
    nid = node.get("id")
    at = f"{where}節 {nid}"
    kind = _kind(node)
    if kind is None:
        out.append(f"{at}: 節の種類が決まりの内に無い（{sorted(node)}）")
        return
    has_t, has_it = "timeout" in node, "idle_timeout" in node
    if kind in TIMED_KEYS:
        if not _is_deadline(node.get("timeout")):
            out.append(f"{at}: {kind} の節の timeout が {DEADLINE} でない（{node.get('timeout')!r}）")
        if has_it:
            out.append(f"{at}: {kind} の節に idle_timeout を書いた")
    elif kind in AI_KEYS:
        if not _is_deadline(node.get("idle_timeout")):
            out.append(f"{at}: AI の節の idle_timeout が {DEADLINE} でない（{node.get('idle_timeout')!r}）")
        if has_t:
            out.append(f"{at}: AI の節に timeout を書いた")
        if not isinstance(node.get("output_format"), dict) or not node["output_format"]:
            out.append(f"{at}: AI の節に output_format が無い")
        sb = node.get("sandbox")
        if not (isinstance(sb, dict) and sb.get("enabled") is True and sb.get("allowUnsandboxedCommands") is False):
            out.append(f"{at}: AI の節の sandbox が {{enabled: true, allowUnsandboxedCommands: false}} でない（{sb!r}）")
        _check_sandbox(sb, node, at, EXCEPTIONS.get((*place, nid), {}), out)
        tools = node.get("allowed_tools")
        allowed = _allowed_tools(place, nid)
        if allowed is not None:
            if not isinstance(tools, list):
                out.append(f"{at}: AI の節に allowed_tools が無い（無ければ全部の道具を持つ）")
            elif not set(tools) <= allowed:
                out.append(f"{at}: AI の節の allowed_tools が {sorted(allowed)} の外を持つ"
                           f"（{sorted(set(tools) - allowed)}）")
        mc = node.get("mutates_checkout", "（無し）")
        if allowed is None or not isinstance(tools, list) or set(tools) & TREE_CHANGERS:
            if mc is False:
                out.append(f"{at}: Bash か書く道具を持つ節に mutates_checkout: false を書いた（受け付けの出し直しが走らなくなる）")
        elif mc is not False:
            out.append(f"{at}: AI の節の mutates_checkout が false でない（{mc!r}。読むだけの節はエンジンにも守らせる）")
        ss = node.get("settingSources", "（無し）")
        if ss != ["user"]:
            out.append(f"{at}: AI の節の settingSources が [user] でない（{ss!r}。役は隔離した設定の置き場"
                       "（dev/toolset.py が組む、選んだ物だけ）を読む）")
        if "skills" in node:
            skills = node["skills"]
            if not (isinstance(skills, list) and skills and all(isinstance(k, str) for k in skills)):
                out.append(f"{at}: AI の節の skills: が名前（文字列）の空でない一覧でない（{skills!r}）")
            elif not set(skills) <= SP_SKILLS | SKILLS_EXTRA.get((*place, nid), frozenset()):
                extra = SKILLS_EXTRA.get((*place, nid), frozenset())
                out.append(f"{at}: AI の節の skills: が借りたスキルの一覧の外を持つ（{sorted(set(skills) - SP_SKILLS - extra)}。"
                           "書けるのは .shared/borrow/borrow.json の superpowers.skills だけ）")
    else:
        if has_t or has_it:
            out.append(f"{at}: {kind} の節に期限（timeout・idle_timeout）を書いた")
    if kind == "loop_group":
        g = node["loop_group"]
        if not isinstance(g, dict):
            out.append(f"{at}: loop_group が表でない")
            return
        want = LOOP_MAX.get((*place, nid), 3)
        if not (type(g.get("max_iterations")) is int and g["max_iterations"] == want):
            out.append(f"{at}: loop_group の max_iterations が {want} でない（{g.get('max_iterations')!r}）")
        if not (isinstance(g.get("until_bash"), str) and g["until_bash"].strip()):
            out.append(f"{at}: loop_group に until_bash が無い")
        for n in g.get("nodes") if isinstance(g.get("nodes"), list) else []:
            if isinstance(n, dict) and _kind(n) == "approval":
                out.append(f"{at} の中の節 {n.get('id')}: loop_group の本体に approval の節を置いた"
                           "（関所の後の再開で輪の会話が欠ける。Archon #3532。関所は輪の外の最上段に置く）")
        _check_nodes(g.get("nodes"), f"{at} の中の", place, out)


def _check_nodes(nodes, where, place, out):
    if not isinstance(nodes, list) or not nodes:
        out.append(f"{where}nodes が無い")
        return
    for n in nodes:
        _check_node(n, where, place, out)


def check_file(path: pathlib.Path) -> list:
    """1 本の工程の YAML の違反の文の一覧（空なら決まりを全部守っている）"""
    path = pathlib.Path(path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    if not isinstance(doc, dict):
        return [f"{path.name}: 工程の YAML が表でない"]
    _check_nodes(doc.get("nodes"), f"{path.name}: ", (path.parent.name, path.name), out)
    return out


class PinnedSkillsCase(unittest.TestCase):
    def test_sp_skills_is_the_borrow_list(self):
        """[user] で許す名前は、借りた写しの名前そのもの（引き方が壊れて空や別の集合にならない）"""
        from test_sp_skills import BORROW
        self.assertEqual(SP_SKILLS, BORROW)


class YamlRulesCase(unittest.TestCase):
    def assertOneRule(self, found, part, what):
        """違反がちょうど 1 つで、その文面が part を含む（件数だけでは狙いの決まりが当たったか分からない）"""
        self.assertEqual([part in f for f in found], [True],
                         f"{what}: 違反はちょうど 1 つで {part!r} を含むはず: {found}")

    def test_each_bad_yaml_is_red(self):
        bad = sorted((TESTS / "yaml_bad").glob("*.yaml"))
        self.assertGreaterEqual(len(bad), 5)
        # 期待の無い見本・見本の無い期待を許さない
        self.assertEqual({p.stem for p in bad}, set(BAD_EXPECT))
        for p in bad:
            with self.subTest(p.name):
                self.assertOneRule(check_file(p), f"{p.name}: {BAD_EXPECT[p.stem]}", p.name)

    def test_good_yaml_is_green(self):
        good = sorted((TESTS / "yaml_good").glob("*.yaml"))
        self.assertTrue(good)
        for p in good:
            with self.subTest(p.name):
                self.assertEqual(check_file(p), [])

    def test_pack_yaml_is_green(self):
        files = sorted(ROOT.glob("*/*.yaml"))
        for p in files:
            with self.subTest(str(p.relative_to(ROOT))):
                self.assertEqual(check_file(p), [])

    def test_all_ai_nodes_user_settings(self):
        """pack の全部の AI の節（輪の中も）が settingSources: [user]（隔離した設定だけを読む。P1 計画 Task 20）。
        節を 1 つも見つけられない空回りも赤"""
        def ai_nodes(nodes):
            for n in nodes or []:
                if isinstance(n, dict):
                    if _kind(n) in AI_KEYS:
                        yield n.get("id"), n.get("settingSources")
                    yield from ai_nodes((n.get("loop_group") or {}).get("nodes"))
        found = []
        for p in sorted(ROOT.glob("*/*.yaml")):
            found += [(p.name, *row) for row in ai_nodes(yaml.safe_load(p.read_text(encoding="utf-8")).get("nodes"))]
        self.assertGreaterEqual(len(found), 7, found)
        self.assertEqual([f for f in found if f[2] != ["user"]], [])

    def test_user_scope_only_under_curated_config(self):
        """[user] を許すのは、節がいつも選んだ物だけの隔離した設定で起きるから（test_pack_lines_do_not_use_user_scope_yet を
        置き換えた。C21）。Archon を起こすのは dev/archon.sh の exec だけで、その前に CLAUDE_CONFIG_DIR を殻の中の置き場に
        固定し、どちらの道（認証あり・なし）でも toolset.py install（組む・柵に当たれば set -e で止まる）を通す。
        殻が組まずに Archon を起こせる形になったら、[user] は利用者の CLAUDE.md・hooks を読みうるので赤。
        振る舞いは tests/test_dev.py（test_archon_sh_installs_borrowed_skills・test_archon_sh_stops_when_isolated_config_leaks_into_user_scope）
        と tests/test_toolset.py が縛る"""
        dev = ROOT / "dev"
        lines = [ln.strip() for ln in (dev / "archon.sh").read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        self.assertIn("set -eu", lines)
        execs = [i for i, ln in enumerate(lines) if ln.startswith("exec ")]
        self.assertEqual([lines[i] for i in execs], [
            'exec python3 -I "$AUTH_LAUNCH" exec --for archon.sh --user-home "$USER_HOME" --user-config "$USER_CONFIG_RAW" '
            '-- "$BIN_PATH" "$@"'])
        fixed = [i for i, ln in enumerate(lines) if ln == 'CLAUDE_CONFIG_DIR="$WORKS_DEV_HOME/claude-config"']
        installs = [i for i, ln in enumerate(lines) if ln.startswith('python3 "$TOOLSET" install ')]
        self.assertEqual(len(fixed), 1, "CLAUDE_CONFIG_DIR を殻の中の置き場に固定していない")
        self.assertEqual(len(installs), 2, "認証あり・なしの両方の道で toolset.py install を通していない")
        self.assertTrue(fixed[0] < min(installs) and max(installs) < execs[0], "組む前か、組んだ後の外で Archon を起こす")
        # ほかの殻は Archon の実行ファイルを直に起こさない（archon.sh を通す）
        for sh in sorted(dev.glob("*.sh")):
            if sh.name != "archon.sh":
                with self.subTest(sh.name):
                    self.assertNotIn("archon-darwin", sh.read_text(encoding="utf-8"))

    def test_writer_allowed_only_in_blk_fix(self):
        body = (TESTS / "yaml_bad" / "fix_outside_blk_fix.yaml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            outside = "AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash', 'Edit', 'Write']）"
            for folder, name, want in (("blk-fix", "blk-fix.yaml", None), ("blk-judge", "blk-fix.yaml", outside),
                                       ("blk-fix", "other.yaml", outside)):
                p = pathlib.Path(tmp) / folder / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
                with self.subTest(f"{folder}/{name}"):
                    if want is None:
                        self.assertEqual(check_file(p), [])
                    else:
                        self.assertOneRule(check_file(p), f"{name}: 節 fix: {want}", f"{folder}/{name}")
            # blk-fix の中でも fix 以外の節は読むだけの道具に限る
            p = pathlib.Path(tmp) / "blk-fix" / "blk-fix.yaml"
            p.write_text(body.replace("id: fix", "id: accept-fix"), encoding="utf-8")
            self.assertOneRule(check_file(p), f"blk-fix.yaml: 節 accept-fix: {outside}", "blk-fix/accept-fix")

    def test_web_reader_only_in_table(self):
        """web の道具（WebSearch・WebFetch）を持ってよいのは表 EXCEPTIONS の節だけ（読むだけの目・読むだけの本線の審査は持たない）"""
        body = (TESTS / "yaml_good" / "all_kinds.yaml").read_text(encoding="utf-8")
        doc = yaml.safe_load(body)
        ai = next(n for n in doc["nodes"] if "command" in n or "prompt" in n)
        ai["allowed_tools"] = ["Read", "WebSearch", "WebFetch"]
        with tempfile.TemporaryDirectory() as tmp:
            for folder, nid, ok in (("blk-eyes", "r1-minimality", True), ("blk-eyes", "premise-check", True),
                                    ("blk-eyes", "r3-coherence", False), ("blk-judge", "r1-minimality", False),
                                    ("blk-judge", "judge", True), ("blk-delta", "review", False),
                                    ("blk-refix", "review2", False)):
                ai["id"] = nid
                p = pathlib.Path(tmp) / folder / f"{folder}.yaml"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
                with self.subTest(f"{folder}/{nid}"):
                    found = [f for f in check_file(p) if "allowed_tools" in f]
                    self.assertEqual(found == [], ok, found)

    def test_bash_reader_only_in_blk_ci(self):
        """Bash を足してよいのは blk-ci/blk-ci.yaml の節 ci だけ。そこでも書く道具（Edit・Write）は持てない"""
        body = (TESTS / "yaml_bad" / "bash_outside_blk_ci.yaml").read_text(encoding="utf-8")
        narrow = "sandbox: {enabled: true, allowUnsandboxedCommands: false}"
        self.assertIn(narrow, body)
        # 表の節 ci の形（広い sandbox と旗）にした同じ節
        wide = body.replace(narrow, "sandbox: " + json.dumps(DELEGATE_SANDBOX)).replace(
            "output_format: {type: object}", "output_format: {type: object, description: 'works-node: ci no-tree-write'}")
        with tempfile.TemporaryDirectory() as tmp:
            outside = "AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash']）"
            for folder, name, want in (("blk-ci", "blk-ci.yaml", None), ("blk-judge", "blk-ci.yaml", outside),
                                       ("blk-ci", "other.yaml", outside)):
                p = pathlib.Path(tmp) / folder / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(wide if want is None else body, encoding="utf-8")
                with self.subTest(f"{folder}/{name}"):
                    if want is None:
                        self.assertEqual(check_file(p), [])
                    else:
                        self.assertOneRule(check_file(p), f"{name}: 節 ci: {want}", f"{folder}/{name}")
            p = pathlib.Path(tmp) / "blk-ci" / "blk-ci.yaml"
            # blk-ci の ci でも書く道具は持てない
            p.write_text(wide.replace("[Read, Grep, Glob, Bash]", "[Read, Grep, Glob, Bash, Edit]"), encoding="utf-8")
            self.assertOneRule(check_file(p), "blk-ci.yaml: 節 ci: AI の節の allowed_tools が ['Bash', 'Glob', 'Grep', 'Read', 'WebFetch', 'WebSearch'] の外を持つ（['Edit']）",
                               "blk-ci/ci+Edit")
            # blk-ci の中でも ci 以外の節は読むだけの道具に限る
            p.write_text(body.replace("id: ci", "id: ci-accept"), encoding="utf-8")
            self.assertOneRule(check_file(p), f"blk-ci.yaml: 節 ci-accept: {outside}", "blk-ci/ci-accept")

    def test_wide_sandbox_only_in_table(self):
        """広い sandbox（graphloops の任せ先と同じ形）を持ってよいのは表 EXCEPTIONS の節だけで、形は表のとおり、
        印に旗 no-tree-write を持つ（包みが本物の作業ツリーを守る。裁定 R56）"""
        real = yaml.safe_load((ROOT / "blk-ci" / "blk-ci.yaml").read_text(encoding="utf-8"))
        loop = next(n for n in real["nodes"] if n["id"] == "ci-loop")
        ci = next(m for m in loop["loop_group"]["nodes"] if m["id"] == "ci")
        self.assertEqual(ci["sandbox"], EXCEPTIONS[("blk-ci", "blk-ci.yaml", "ci")]["sandbox"])
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "blk-ci" / "blk-ci.yaml"
            p.parent.mkdir()

            def found(**change):
                node = dict(ci, **change)
                doc = {"name": "x", "nodes": [node]}
                p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
                return check_file(p)
            self.assertEqual(found(), [])
            self.assertOneRule(found(sandbox={"enabled": True, "allowUnsandboxedCommands": False}),
                               "blk-ci.yaml: 節 ci: AI の節の sandbox が表の形でない", "狭い sandbox")
            wider = dict(ci["sandbox"], excludedCommands=["git"])
            self.assertOneRule(found(sandbox=wider), "blk-ci.yaml: 節 ci: AI の節の sandbox が表の形でない", "鍵を足した")
            self.assertOneRule(found(output_format=dict(ci["output_format"], description="works-node: ci")),
                               "blk-ci.yaml: 節 ci: 広い sandbox の節の印に旗 no-tree-write が無い", "旗なし")
            # 同じ節を表の外（別のフォルダ）に置くと、Bash と広い sandbox の 2 つが外れる
            q = pathlib.Path(tmp) / "blk-judge" / "blk-ci.yaml"
            q.parent.mkdir()
            q.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            p.unlink()
            out = check_file(q)
            self.assertEqual(len(out), 2, out)
            self.assertTrue(any("広げる鍵を持つ" in f for f in out), out)
            self.assertTrue(any("allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash', 'WebFetch', 'WebSearch']）" in f for f in out), out)

    def test_failIfUnavailable_is_not_wide(self):
        """failIfUnavailable（sandbox が立たない場で素通しにしない）は狭める鍵なので、どの AI の節も持ってよい"""
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "w.yaml"
            p.write_text("nodes:\n  - id: judge\n    prompt: 判定せよ\n    allowed_tools: [Read]\n    settingSources: [user]\n"
                         "    sandbox: {enabled: true, allowUnsandboxedCommands: false, failIfUnavailable: true}\n"
                         "    idle_timeout: 1728000000\n    output_format: {type: object}\n    mutates_checkout: false\n",
                         encoding="utf-8")
            self.assertEqual(check_file(p), [])

    def test_measurer_allowed_only_in_blk_premises(self):
        body = (TESTS / "yaml_bad" / "measure_outside_blk_premises.yaml").read_text(encoding="utf-8")
        read_only = "AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash']）"
        with tempfile.TemporaryDirectory() as tmp:
            for folder, name, want in (("blk-premises", "blk-premises.yaml", None),
                                       ("blk-judge", "blk-premises.yaml", read_only),
                                       ("blk-premises", "other.yaml", read_only),
                                       ("blk-fix", "blk-fix.yaml", read_only)):   # 書く役の置き場でも節の名前が違えば外
                p = pathlib.Path(tmp) / folder / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
                with self.subTest(f"{folder}/{name}"):
                    if want is None:
                        self.assertEqual(check_file(p), [])
                    else:
                        self.assertOneRule(check_file(p), f"{name}: 節 premises: {want}", f"{folder}/{name}")
            p = pathlib.Path(tmp) / "blk-premises" / "blk-premises.yaml"
            # 測る役でも書く道具は外
            p.write_text(body.replace("[Read, Grep, Glob, Bash]", "[Read, Grep, Glob, Bash, Edit, Write]"), encoding="utf-8")
            self.assertOneRule(check_file(p), "blk-premises.yaml: 節 premises: AI の節の allowed_tools が "
                               "['Bash', 'Glob', 'Grep', 'Read', 'WebFetch', 'WebSearch'] の外を持つ（['Edit', 'Write']）", "premises + Edit")
            # blk-premises の中でも premises 以外の節は読むだけの道具に限る
            p.write_text(body.replace("id: premises", "id: premises-accept"), encoding="utf-8")
            self.assertOneRule(check_file(p), f"blk-premises.yaml: 節 premises-accept: {read_only}", "premises-accept")

    def test_bundled_skills_only_in_local_review(self):
        """Claude Code に同梱のスキル（BUNDLED_SKILLS）を skills: に書いてよいのは blk-material の節 local-review だけ（表 SKILLS_EXTRA）"""
        body = (TESTS / "yaml_good" / "all_kinds.yaml").read_text(encoding="utf-8")
        doc = yaml.safe_load(body)
        ai = next(n for n in doc["nodes"] if "command" in n or "prompt" in n)
        ai["skills"] = ["code-review", "simplify", "security-review", "test-driven-development"]
        with tempfile.TemporaryDirectory() as tmp:
            for folder, name, nid, ok in (("blk-material", "blk-material.yaml", "local-review", True),
                                          ("blk-material", "blk-material.yaml", "hygiene", False),
                                          ("blk-judge", "blk-material.yaml", "local-review", False),
                                          ("blk-material", "other.yaml", "local-review", False)):
                ai["id"] = nid
                p = pathlib.Path(tmp) / folder / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
                with self.subTest(f"{folder}/{name}/{nid}"):
                    found = [f for f in check_file(p) if "skills:" in f]
                    if ok:
                        self.assertEqual(found, [])
                    else:
                        self.assertEqual(len(found), 1, found)
                        self.assertIn("借りたスキルの一覧の外を持つ（['code-review', 'security-review', 'simplify']", found[0])
            # 外れの節でも同梱の 3 つと借りた物のほかは外
            ai["id"], ai["skills"] = "local-review", ["code-review", "brainstorming"]
            p = pathlib.Path(tmp) / "blk-material" / "blk-material.yaml"
            p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
            found = [f for f in check_file(p) if "skills:" in f]
            self.assertEqual(len(found), 1, found)
            self.assertIn("外を持つ（['brainstorming']", found[0])

    def test_setting_sources_user_only(self):
        base = ("nodes:\n  - id: judge\n    prompt: 判定せよ\n    allowed_tools: [Read]\n"
                "    sandbox: {enabled: true, allowUnsandboxedCommands: false}\n"
                "    idle_timeout: 1728000000\n    output_format: {type: object}\n    mutates_checkout: false\n")
        with tempfile.TemporaryDirectory() as tmp:
            bad = "w.yaml: 節 judge: AI の節の settingSources が [user] でない"
            outside = "w.yaml: 節 judge: AI の節の skills: が借りたスキルの一覧の外を持つ"
            shape = "w.yaml: 節 judge: AI の節の skills: が名前（文字列）の空でない一覧でない"
            for extra, want in (("    settingSources: [user]\n", None),
                                ("    skills: [test-driven-development]\n    settingSources: [user]\n", None),
                                ("    settingSources: []\n", f"{bad}（[]。"),
                                ("    settingSources: [project]\n", f"{bad}（['project']。"),
                                ("    settingSources: [project, user]\n", f"{bad}（['project', 'user']。"),
                                ("    skills: [test-driven-development]\n", f"{bad}（'（無し）'。"),
                                ("    skills: [x]\n    settingSources: [user]\n", f"{outside}（['x']"),
                                ("    skills: []\n    settingSources: [user]\n", f"{shape}（[]）"),
                                ("    skills: [{name: test-driven-development}]\n    settingSources: [user]\n", shape)):
                p = pathlib.Path(tmp) / "w.yaml"
                p.write_text(base + extra, encoding="utf-8")
                with self.subTest(extra):
                    found = check_file(p)
                    if want is None:
                        self.assertEqual(found, [])
                    else:
                        self.assertOneRule(found, want, extra)


def _is_ai(node):
    return _kind(node) in AI_KEYS or _kind(node) == "include"   # include は中に AI の節を持ちうる


def _ancestors(nid, by_id):
    seen, todo = set(), list(by_id[nid].get("depends_on") or [])
    while todo:
        d = todo.pop()
        if d in by_id and d not in seen:
            seen.add(d)
            todo.extend(by_id[d].get("depends_on") or [])
    return seen


def _loop_chains(nodes, rid, chain=()):
    """役 rid を直に持つ輪までの包みの列 ((その段の節の並び, 輪), …)（入れ子の輪も辿る。外から内の順）"""
    for n in nodes or []:
        if _kind(n) != "loop_group":
            continue
        inner = n["loop_group"]["nodes"]
        here = (*chain, (nodes, n))
        if any(m.get("id") == rid for m in inner):
            yield here
        else:
            yield from _loop_chains(inner, rid, here)


class RoleSessionCase(unittest.TestCase):
    """役の節は、CLAUDE.md を読んだ前の会話を引き継がない（settingSources: [user] が効くのは新しい会話だけ）。

    輪の中の役に context: fresh は書けない（受け付けが拒んだ時の同じ会話での出し直しが壊れる）。代わりに形で守る:
    役はブロックの輪（loop_group）の中に居て、ブロックの中で役より前（depends_on を辿った先）に AI の節も include も無い。
    Archon は輪の 1 周目をいつも新しい会話で起こし（dag-executor.ts:5069）、include の入口の節は外の会話を
    引き継がない（dag-executor.ts:10417-10427）。2 周目からの出し直しは、1 周目の settingSources: [user] の会話の続き。
    """

    def test_role_is_first_ai_node_in_its_block_loop(self):
        for folder, name, rid in ROLES:
            with self.subTest(f"{folder}/{rid}"):
                doc = yaml.safe_load((ROOT / folder / name).read_text(encoding="utf-8"))
                chains = list(_loop_chains(doc["nodes"], rid))
                self.assertEqual(len(chains), 1, f"{rid} が輪の中にちょうど 1 つ居ない")
                grp = chains[0][-1][1]
                inner = {m["id"]: m for m in grp["loop_group"]["nodes"]}
                role = inner[rid]
                self.assertEqual(role.get("settingSources"), ["user"])
                self.assertNotIn("context", role, "輪の中の役に context を書くと同じ会話での出し直しが壊れる")
                # 役の輪の中の前と、役の輪を包む各段（入れ子の輪の外の輪・ブロックの頭）で輪より前に在る節
                before = [inner[a] for a in _ancestors(rid, inner)]
                for level, g in chains[0]:
                    by_id = {n["id"]: n for n in level}
                    before += [by_id[a] for a in _ancestors(g["id"], by_id)]
                self.assertEqual([n["id"] for n in before if _is_ai(n)], [],
                                 f"{rid} より前に AI の節か include が在る（前の会話を引き継ぐ恐れ）")
                others = [m["id"] for m in inner.values() if m["id"] != rid and _is_ai(m)]
                self.assertEqual(others, [], f"{rid} の輪に別の AI の節が在る")


class MutatesCheckoutCase(unittest.TestCase):
    """節の段の mutates_checkout: false は、書く役でなく作業ツリーを変える道具（TREE_CHANGERS）も持たない AI の節にだけ在る"""
    CHANGERS = TREE_CHANGERS

    def _found(self, folder, name, nid, tools, extra=""):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / folder / name
            p.parent.mkdir(parents=True)
            p.write_text(f"nodes:\n  - id: {nid}\n    prompt: 読め\n    allowed_tools: {tools}\n    settingSources: [user]\n"
                         "    sandbox: {enabled: true, allowUnsandboxedCommands: false}\n"
                         "    idle_timeout: 1728000000\n    output_format: {type: object}\n" + extra, encoding="utf-8")
            return check_file(p)

    def test_pack_read_only_ai_nodes_do_not_mutate_checkout(self):
        def ai_nodes(place, nodes):
            for n in nodes or []:
                if isinstance(n, dict):
                    if _kind(n) in AI_KEYS:
                        yield n
                    yield from ai_nodes(place, (n.get("loop_group") or {}).get("nodes"))
        read_only, changers = [], []
        for p in sorted(ROOT.glob("*/*.yaml")):
            place = (p.parent.name, p.name)
            for n in ai_nodes(place, yaml.safe_load(p.read_text(encoding="utf-8")).get("nodes")):
                changes = (_allowed_tools(place, n.get("id")) is None
                           or bool(set(n.get("allowed_tools") or []) & self.CHANGERS))
                (changers if changes else read_only).append((p.name, n.get("id"), n.get("mutates_checkout", "（無し）")))
        self.assertGreaterEqual(len(read_only), 20, read_only)
        self.assertEqual([r for r in read_only if r[2] is not False], [], "読むだけの節に mutates_checkout: false が無い")
        self.assertEqual([r for r in changers if r[2] is False], [], "Bash か書く道具を持つ節に mutates_checkout: false が在る")

    def test_read_only_node_without_mutates_checkout_is_red(self):
        self.assertEqual(self._found("blk-judge", "w.yaml", "judge", "[Read, Grep, Glob]",
                                     "    mutates_checkout: false\n"), [])
        found = self._found("blk-judge", "w.yaml", "judge", "[Read, Grep, Glob]")
        self.assertEqual(["w.yaml: 節 judge: AI の節の mutates_checkout が false でない" in f for f in found], [True], found)
        # 真偽値の false そのものだけを通す（文字列の "false" は Archon にとって偽でない）
        found = self._found("blk-judge", "w.yaml", "judge", "[Read, Grep, Glob]", "    mutates_checkout: 'false'\n")
        self.assertEqual(["w.yaml: 節 judge: AI の節の mutates_checkout が false でない" in f for f in found], [True], found)

    def test_changer_node_with_mutates_checkout_false_is_red(self):
        self.assertEqual(self._found("blk-premises", "blk-premises.yaml", "premises", "[Read, Grep, Glob, Bash]"), [])
        found = self._found("blk-premises", "blk-premises.yaml", "premises", "[Read, Grep, Glob, Bash]",
                            "    mutates_checkout: false\n")
        self.assertEqual(["blk-premises.yaml: 節 premises: Bash か書く道具を持つ節に mutates_checkout: false を書いた" in f
                          for f in found], [True], found)
        # 書く役（道具の決まりの外）も同じ
        found = self._found("blk-fix", "blk-fix.yaml", "fix", "[Read, Edit, Write, Bash]", "    mutates_checkout: false\n")
        self.assertEqual(["blk-fix.yaml: 節 fix: Bash か書く道具を持つ節に mutates_checkout: false を書いた" in f
                          for f in found], [True], found)


if __name__ == "__main__":
    unittest.main()
