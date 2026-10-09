"""works のテストの段（fast・heavy）の一覧と、段を 1 つ選んで回す入口。

run.sh が `python3 tests/tiers.py <段> [unittest の引数]` で起こす（WORKS_TESTS が空なら段 all＝discover の全部。
fast・heavy と違い、段の一覧の食い違いでも止めず、一覧に書き忘れたモジュールも回す）。
どの段も終わりに見送りの門（SkipGateRunner）を通す: 見送りの理由は root の約束『SKIP <能力>: <理由>』で書き、
環境変数 FAIL_ON_SKIP=1 のとき、能力が SKIP_ALLOW（空白かカンマ区切り）に無い見送りと名前の無い見送りを失敗に数える
（約束の正本は tests/run.sh の report_skips と graphloops/tests/py/fence.py。works は graphloops を持たない pack として
対象へ写されるので、判定は写しで持つ）。FAIL_ON_SKIP が無ければ見送りの一覧を出すだけ。
TDD の実行器 dev/tdd-suite.sh（pytest で回す）は `python3 tests/tiers.py paths <段>` で段のファイルの一覧を引く。
一覧に書くのは fast（FAST）だけで、heavy は FAST に無い全部（tests/test_*.py）。書き忘れた新しいモジュールは heavy に
入る（重いテストが黙って fast に入らない側に倒れる）。FAST に在るのにファイルが無い名前があると、段を選んだ実行は
終了コード 2 で止まり、test_tiers も赤になる。

組（shard）: 環境変数 WORKS_SHARD=<番号>/<組の数>（番号は 0 起点）で、段の中のモジュールを組に分けてその 1 組だけを回す
（CI の works の job が組ごとに別の runner で並べる）。分け方は shard_of で、discover が拾う全部のモジュールを重さの
目安（weight）の大きい順に、その時いちばん軽い組へ配る（決まっていて、どの runner でも同じ表になる）。組の和は
ちょうど全部で重ならない（test_tiers が組の数 1〜8 で縛る。新しいモジュールは書き足さなくてもどれかの組に入る）。
読んだ WORKS_SHARD は消してから試験を起こす（中の試験が起こす run.sh・tiers.py に組を継がせない）。
`python3 tests/tiers.py list <段>` は回すモジュールの名前を 1 行ずつ出すだけ（WORKS_SHARD が在れば組の分だけ）。

heavy に置く物: 試験ごとに git のリポジトリを作る（git init・commit・mktarget・dogfood の clone）・uv run を起こす・
Archon を起こす・golden を再生する・プロセスの木を起こす・決まった秒を待つ。短くても、これらを使うモジュールは heavy に置く
（負荷の高い機械では git と子のプロセスが遅れの元になる）。種の git を tests/gitkit.py の型（プロセスに 1 回だけ作る）の
写しで配るだけなら、試験ごとに作るに当たらない。段は使う物の形で分ける（決まっていて、読めば確かめられる）。
fast は秒の上限ではない（負荷の高い機械では fast の中の git・子のプロセスも遅れる）。
"""
import json
import os
import pathlib
import re
import sys
import time
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
PATTERN = "test_*.py"   # run.sh の discover と同じ

# fast に置くモジュールと、置ける訳（使う物の形）。ここに無いモジュールは heavy
FAST = frozenset({
    "test_blk_judge",       # 種の git は gitkit の型の写し・スクリプトを子で起こす
    "test_core_copy",       # 写しの置き場のファイルを読むだけ
    "test_structure_units", # 判定の単位を契約の形に写す関数（一時の置き場のファイルだけ。git・子のプロセスを使わない）
    "test_structure_eye",   # 構造の目の受け付け・出口・境の落ち所（一時の置き場のファイルと collect.py を子で起こすだけ。git を使わない）
    "test_core_verbatim",   # 写しと元の commit のバイト一致（git show で読むだけ。リポジトリを作らない）
    "test_core_sync",       # 写し直しの道具: 偽の正本の git はモジュールに 1 回だけ作り、試験は道具を子で起こして git show で読むだけ
    "test_scopes",          # 部品の置き場（依頼 239）: flow_adapter の env の読みと manifest の照らし（一時の置き場のファイルだけ）
    "test_gitkit",          # gitkit の型を 1 回作って 2 回写す
    "test_unittrees",       # 単位の worktree（種の git は gitkit の型の写し。試験ごとに worktree を 2〜3 本切る・子のプロセスは git だけ）
    "test_tdd_lane_wiring", # TDD の輪の並べの節の配線（YAML・筋書き・状態の JSON を読むだけ。git・子のプロセスなし）
    "test_fix_lane_wiring", # 修正役の並べの節の配線と並べの枝の部品の純粋な口（YAML・筋書き・表を読むだけ。git・盤面・子のプロセスなし）
    "test_lanekit",         # 並べの枝の部品の純粋な口と枝の数の写しの縛り（一時の置き場のファイル 1 つ・表を読むだけ。git・子のプロセスなし）
    "test_unitlanes",       # 下請けを単位の worktree で並べる（種の git は gitkit の型の写し。試験ごとに worktree を 2〜3 本切る・子のプロセスは git と python3 1 本）
    "test_blk_eyes_lanes",  # 独立の目の筋の順: YAML と Archon の trigger_rule の写しで節を回す（盤面の fixture を読むだけ。git・子のプロセスを使わない）
    "test_layers",          # 層と依存の向き（裁定 R59）: pack のファイルと YAML を読むだけ
    "test_block_blind",     # ブロックの散文のほかのブロックの名指しの柵と、役の指示書のほかの役・段の語の柵: git ls-files と追跡されたファイルを読むだけ（子のプロセスは git だけ）
    "test_concept_fences",  # 考えの住処の柵（地図 docs/concepts.md と表 docs/concepts.json）: git ls-files と追跡されたファイルを読むだけ（子のプロセスは git だけ）
    "test_impact",          # 変更の周りの地図: 種の git は gitkit の型の写し・git ls-files と diff を読む（子のプロセスは git だけ）
    "test_halt",            # 線 A: 止め札を一時の盤面に置く・stop.sh を偽の Archon（sh の台本）で起こす・python を 8 本同時に起こす（git・uv・木なし）
    "test_node_marker",     # 線 A: 印の文字列を組んで読むだけ
    "test_gh_port",         # 役が読むだけの gh を呼ぶ形の柵: 指示書の md と YAML を読むだけ（git・子のプロセスなし）
    "test_forge",           # forge の無い remote の決め（forge.py）と盤面への差し替え・報告の 1 行・ghreads の条件外: 関数を直に呼ぶ・偽の盤面・git init と remote add・偽の gh（盤面・子の実行器なし）
    "test_gate_na",         # ゲートの検算の役の『条件外』の差し替えとゲートの印: 関数を直に呼ぶ・偽の盤面・一時の置き場に差分のファイル（git・盤面・子のプロセスなし）
    "test_hostgh",          # run の中で利用者の gh を継ぐ口（dev/hostgh.py）: 関数を直に呼ぶ・偽の gh と sh の口を子で起こすだけ（git・盤面なし）
    "test_carry_ci",        # run の後の CI の赤を次の依頼の prior_failures へ（ghreads.carry_ci）: 関数を直に呼ぶ・ghreads.py を python3 -I で起こすだけ（git・盤面なし）
    "test_depth",           # 単位ごとの深さ（darkfactory/lib/depth.py）: 関数を直に呼ぶ・一時の置き場に書くだけ（盤面・git・子のプロセスなし）
    "test_holeties",        # 差分の審査の穴の枝の名札（holeties と refix.hole_ties）: 関数を直に呼ぶ・偽の盤面（一時の置き場のファイル）だけ（git・子のプロセスなし）
    "test_judge_verify",    # 判定の根を開く（blk-judge/lib/judgeverify.py・申し送りの節・報告の行）: 偽の盤面で関数を直に呼ぶ・一時の置き場に書くだけ（盤面・git・子のプロセスなし）
    "test_ripple",          # 波及の一覧（blk-plan/lib/ripple.py）: 種の git は gitkit の型の写し・子のプロセスは git grep だけ
    "test_consult",         # 範囲の相談の節（blk-fix/lib/consult.py・包みの旗 self-resume・YAML の形）: 偽の盤面で関数を直に呼ぶ・adapter.plan を直に呼ぶ（git・子のプロセスなし）
    "test_fix_rules",       # R65: 修正の決まりの正本と 2 つの指示書の組み立てを、関数を直に呼んで見る（盤面・git・子のプロセスなし）
    "test_conflict_kinds",  # 申し出の種類と裁定 fix_plan_item: 関数を直に呼ぶ・一時の置き場に書くだけ（盤面・git・子のプロセスなし）
    "test_fix_units",       # 修正の受け付けの閉鎖の表と裁定の出どころ: 関数を直に呼ぶ・一時の置き場に書くだけ（盤面・git・子のプロセスなし）
    "test_diverted",        # 局所レビューの fork のレンズの「見ていない」の印: 関数を直に呼ぶ・一時の置き場のファイルだけ（git・盤面なし）
    "test_rolekit",         # P1 Task 13: 役の節の共通の口を偽の盤面と mock で見る（git・子のプロセスなし）
    "test_sp_skills",       # 借りる superpowers のスキルの一覧と無人の読み替え: borrow.json と md を読むだけ（git・子のプロセスなし）
    "test_seat",            # 借りたスキルの座: 216 の写しと seams.json を読むだけ（写しを一時の置き場に写す 1 本と、g1 の差分のコマンドを gitkit の型の写しで sh で走らせる 1 本を含む。盤面なし）
    "test_canary",          # canary の種・依頼・確かめ役 dev/canary_check.py: 種の写しで python3 を 22 本と git merge-file を 5 本・殻 canary.sh の拒みを sh で 3 本・種の git は gitkit の型の写しで、枝の合わせ（git merge と unittrees の diff・apply）に git を 20 本ほど（リポジトリを作らない）・偽の archon.db と盤面を一時の置き場に置いて殻を子で起こす（Archon なし）・固定材料 canary-fixture-units を種の写し（gitkit の型）に線の start で取り込む（1 回。commit-tree などの git を数本）
    "test_fixmeasure",      # 修正の形の測りと採否の判定 dev/fixmeasure.py: 一時の置き場に sqlite の偽の archon.db と盤面（DiskBoard.create。git なし）を作り、殻を子で起こす（git・Archon なし）
    "test_sp_seam",         # 借りる superpowers の照合と包みの部品: 一時の置き場の偽の版のフォルダを読むだけ（git・子のプロセスなし）
    "test_selfcheck",       # 軽い自己点検: 腕の一覧を読むだけ（--check）と、小さな偽の pack で実行器を子で起こす（git なし）
    "test_script_io",       # python を 1 本起こすだけ（git は使わない）
    "test_tiers",           # 偽の uv・枠の台本で run.sh を起こす
    "test_versions",        # run ごとの版の控え: 一時の置き場に書くだけ・start.py を 1 本起こす（git なし）
    "test_libdocs",         # ライブラリの文書を機械が引く（手元の版・公式）: 一時の置き場と偽の HTTP の口・偽の盤面（網・子のプロセスなし。作業ツリーの一覧に git ls-files を起こす）
    "test_libdocs_local",   # 手元の版を静的に読む: 一時の置き場の偽の .venv・node_modules を読むだけ（網・git・子のプロセスなし）
    "test_libdocs_web",     # 公式の文書を引く: 偽の HTTP の口だけ（網・git・子のプロセスなし）
    "test_tool_parity",     # 役の道具が本線の run_by の定義より少なくないか: YAML と写しの graph を読むだけ
    "test_adapter_lane",    # 包みの旗 lane（並べの枝の役を単位の worktree で起こす）: 種の git は gitkit の型の写し・単位の worktree を 2 本切る・adapter.plan を直に呼ぶ（子のプロセスは git だけ）
    "test_adapter_no_turn", # 包みの子の終わりの種分け: 包みを子で起こし、偽の claude（一時の置き場の python）が決めた行を出す（git・Archon・決まった秒の待ちなし）
    "test_adapter_reply",   # 包みの旗 text-reply（返答の契約）: replycontract・adapter の関数を直に呼ぶ・包みを子で起こし偽の claude（python）が stream-json で答える（git・Archon・決まった秒の待ちなし）
    "test_adapter_spend",   # 包みの費用の見せ直し（会話を替えた起動の result の累計）: adapter の関数を直に呼ぶ・包みを子で起こし偽の claude（python）が result を出す（git・Archon・決まった秒の待ちなし）
    "test_auth_launch",     # 殻の認証の起こし役: 偽の runner で順を見る・起こし役を python3 -I で 1 本起こす（git・keychain なし）
    "test_launch",          # 起動の殻の共通の口 launch.py env: 部品を直に呼ぶ・受け方だけ偽の部品を置いて sh を起こす（git なし）
    "test_toolset",         # 隔離した Claude の設定の組み立てと柵: 一時の置き場に写す・偽の claude（python）を子で起こす（git なし）
    "test_yaml_rules",      # YAML を読むだけ
    "test_line_wiring",     # ラインの配線（表の置き場の include）と筋書きの stub の鍵の揃い: YAML と JSON を読むだけ（git・子のプロセスなし）
    "test_line_inputs",     # 入力の名の集合と script の with の鍵（TA16）: YAML とスクリプトを読み、entry.check_inputs を直に呼び、LineRun を種の git を差し替えて組む（git・子のプロセスなし）
    "test_role_give_up",    # 役の輪が done で抜ける（R50）: YAML を読むだけ（git・子のプロセスなし）
    "test_protect",         # 守りのファイルの一覧: git ls-files を読む・種の git は gitkit の型の写し
    "test_tdd_frozen",      # TDD の輪の凍結と裁定の範囲: 種の git は gitkit の型の写し・凍った時の木（write-tree）を git show で読む（盤面・子の実行器なし）
    "test_tdd_frozen_function_span",  # 裁定の 1 行の指しを関数の幅に広げる: test_tdd_frozen と同じ種の git の写し（盤面・子の実行器なし）
    "test_entry_inputs",    # 変更から入る入口の入力（check_inputs）: 種の git は gitkit の型の写しに commit を 1 本足す（盤面・子の実行器なし）
    "test_report_head",     # 報告の冒頭 3 の interrupted の行: 偽の盤面で head_stop を直に呼ぶ（盤面・git・子のプロセスなし）
    "test_ci_test_cmd",     # run_ci の test_cmd の決まり: 偽の盤面と子を起こさない runner（盤面・git・子のプロセスなし）
    "test_blk_spec_gate",   # 仕様の関所の文: gate_text を直に呼ぶ（盤面・git・子のプロセスなし）
    "test_gate_head",       # 関所の文と報告の冒頭 3 行: gate_text・_final_head・report.head3 を偽の盤面で直に呼ぶ（盤面・git・子のプロセスなし）
    "test_plan_scope",      # 承認済みの修正案の項目と修正の差分の照らし（planscope）: 純粋な関数を直に呼ぶだけ（盤面・git・子のプロセスなし）
    "test_plan_fields",     # 修正案の項目の works の欄（planmarks）: 関数を直に呼ぶ・種を一時の置き場に写すだけ（盤面・git・子のプロセスなし）
    "test_converge",        # 事前審査の壁打ちの決まりと往復の控え（converge）: 偽の盤面で関数を直に呼ぶ・一時の置き場に書くだけ（盤面・git・子のプロセスなし）
    "test_delta_marks",     # 差分の審査の返答の 2 判定の欄（deltamarks）: 関数を直に呼ぶ・偽の b に一時の置き場を持たせるだけ（盤面・git・子のプロセスなし）
    "test_marks",           # 返答の足し欄の住処（marks）: 関数を直に呼ぶ・一時の置き場に控えを書くだけ（盤面・git・子のプロセスなし）
    "test_gate_drafts",     # 関所の項目の推しと無人の run の答えの下書き: test_plan_gate の偽の盤面で直に呼ぶ（盤面・git・子のプロセスなし）
    "test_out_of_purpose",  # 目的の外の所見を次の run の依頼へ運ぶ: 偽の盤面と一時の置き場のファイルだけ（git・子のプロセスなし。受け付けは mock）
    "test_plan_gate",       # 修正前の関所の項目の選別: 写しの RL の human_gate を偽の盤面で直に呼ぶ（盤面・git・子のプロセスなし）
    "test_fix_duty",        # 直す義務と外れた単位の正本と受け付けの拒否: test_plan_gate の偽の盤面と mock の受け付け（盤面・git・子のプロセスなし）
    "test_duty_sets",       # 直す義務の 5 つの集合の突き合わせ: test_fix_duty の偽の盤面と mock の口（盤面・git・子のプロセスなし）
    "test_duty_owner",      # 直す義務の集合を持ち主の外で作り直す式を止める検査: works の .py を AST で読むだけ（git・子のプロセスなし）
    "test_report_cold",     # 報告の書き手の輪の初見の確かめ: YAML と偽の盤面・mock の entry.take（盤面・git・子のプロセスなし）
    "test_testcmd_check",   # start の test_cmd の知らせ dev/testcmd_check.py: 種の git は gitkit の型の写し・殻を python3 -I で子で起こす（中の git は check-ignore だけ）
    "test_model_override",  # run の明示の模型で前付けの無い段を起こす: adapter.plan を直に呼ぶ・包みを子で起こし偽の claude（python）が argv を書く（子のプロセスは包みと git rev-parse だけ。Archon・待ちなし）
    "test_graphmap",        # 工程の地図と包みの差し込みの表: 種の YAML と地図の元を読む・adapter.plan を直に呼ぶ・CLI を python3 で子で 4 本（git なし）
    "test_dev_model",       # 殻の全体の模型の明示と既定: 殻を読む・archon.sh と use.sh を偽の Archon で子で起こす（種の git は gitkit の型の写し・切り離し・待ちなし）
})


TIERS = ("fast", "heavy")

# 組に配る重さ: CI で測ったモジュールごとの秒（tests/shard-seconds.json。測った日と run は同じファイルに書く）。記録に無い
# モジュール（後で足した物）は、試験の数（def test_ の行）× 段ごとの 1 本の秒（同じファイルの per_test）。取り直すときは
# 走りの終わりに出る「モジュールごとの秒」の行を写す
_RECORD = json.loads((TESTS / "shard-seconds.json").read_text(encoding="utf-8"))
SECONDS = dict(_RECORD["seconds"])
PER_TEST = dict(_RECORD["per_test"])


def weight(name):
    if name in SECONDS:
        return float(SECONDS[name])
    src = (TESTS / f"{name}.py").read_text(encoding="utf-8")
    n = max(1, len(re.findall(r"^\s*def test_", src, re.M)))
    return n * float(PER_TEST["fast" if name in FAST else "heavy"])


def shard_of(names, total):
    """名前の一覧を total 組に分けた {組の番号: [名前…]}。重い順（同じ重さは名前の順）に、その時いちばん軽い組（同じなら番号の小さい組）へ配る"""
    groups = {i: [] for i in range(total)}
    load = [0.0] * total
    for name in sorted(names, key=lambda m: (-weight(m), m)):
        i = min(range(total), key=lambda k: (load[k], k))
        groups[i].append(name)
        load[i] += weight(name)
    return {i: sorted(g) for i, g in groups.items()}


def shard_env(environ):
    """WORKS_SHARD（<番号>/<組の数>。番号は 0 起点）を (番号, 組の数) で返す。無ければ None、形が違えば ValueError"""
    raw = environ.get("WORKS_SHARD", "")
    if raw == "":
        return None
    m = re.fullmatch(r"([0-9]+)/([1-9][0-9]*)", raw)
    if not m or int(m.group(1)) >= int(m.group(2)):
        raise ValueError(f"WORKS_SHARD は <番号>/<組の数>（番号は 0 起点で組の数より小さい。例 0/4）（今の値: {raw}）")
    return int(m.group(1)), int(m.group(2))


def modules():
    """unittest discover（-s tests -p test_*.py）が拾うモジュールの名前。tests/ の下に package は置かない"""
    return sorted(p.stem for p in TESTS.glob(PATTERN))


def tier_modules(tier):
    """段のモジュールの名前の集合: fast は FAST、heavy は discover が拾う全部のうち FAST に無い物"""
    return set(FAST) if tier == "fast" else set(modules()) - FAST


def problems():
    """段の一覧の食い違いを文の一覧で返す（空なら揃っている）"""
    gone = sorted(FAST - set(modules()))
    return ["FAST に在るのにファイルが無い: " + ", ".join(gone)] if gone else []


class TierLoader(unittest.TestLoader):
    """discover の中で、段に入っていないモジュールのテストを空にする（-k・-p などの引数は discover がそのまま扱う）"""

    def __init__(self, keep):
        super().__init__()
        self.keep = keep

    def loadTestsFromModule(self, module, *args, **kwargs):
        if module.__name__ not in self.keep:
            return self.suiteClass([])
        return super().loadTestsFromModule(module, *args, **kwargs)


SKIP_DECL = re.compile(r"^SKIP ([a-z0-9][a-z0-9-]*): ")


class SkipGateResult(unittest.TextTestResult):
    """走りの終わりに見送り（self.skipped。setUpClass・setUpModule の SkipTest も入る）を一覧に出し、門を当てる"""

    skip_gate_failed = 0

    def startTestRun(self):
        super().startTestRun()
        self._works_last = time.monotonic()

    def stopTest(self, test):
        # 前の試験の終わり（走りの頭）からの間をこの試験のモジュールに数える。setUpModule・setUpClass の秒が入る
        # （前のクラスの tearDownClass の秒も次の試験に入る）
        super().stopTest(test)
        now = time.monotonic()
        secs = getattr(self, "_works_secs", None)
        if secs is None:
            secs = self._works_secs = {}
        mod = type(test).__module__
        secs[mod] = secs.get(mod, 0.0) + now - getattr(self, "_works_last", now)
        self._works_last = now

    def printErrors(self):
        super().printErrors()
        # モジュールごとの秒（setUpModule・setUpClass の秒も入る）。組の重さ tests/shard-seconds.json へ写す材料
        secs = getattr(self, "_works_secs", {})
        if secs:
            self.stream.writeln("モジュールごとの秒: " + " ".join(
                f"{m}={v:.0f}" for m, v in sorted(secs.items(), key=lambda kv: (-kv[1], kv[0]))))
        # 環境は走りの中で 1 回だけ読む（wasSuccessful は走りの後にも呼ばれる）
        allow = set(re.split(r"[\s,]+", os.environ.get("SKIP_ALLOW", ""))) - {""}
        strict = os.environ.get("FAIL_ON_SKIP") == "1"
        bad = 0
        if self.skipped:
            self.stream.writeln(f"見送り（{len(self.skipped)} 件）:")
        for test, reason in self.skipped:
            m = SKIP_DECL.match(reason)
            if m and m.group(1) in allow:
                why = "（SKIP_ALLOW で許した）"
            else:
                bad += 1
                why = "（SKIP_ALLOW に無い）" if m else "（名前の無い見送り。『SKIP <能力>: <理由>』で書く）"
            self.stream.writeln(f"  {test.id()}: {reason} {why}")
        if strict and bad:
            self.skip_gate_failed = bad
            self.stream.writeln(f"見送りを失敗に数えた: {bad} 件（FAIL_ON_SKIP=1）")
        self.stream.flush()

    def wasSuccessful(self):
        return super().wasSuccessful() and not self.skip_gate_failed


class SkipGateRunner(unittest.TextTestRunner):
    resultclass = SkipGateResult

    def run(self, test):
        # TestSuite は回した試験を自分の一覧から外す（_cleanup）。渡された一覧は写しで回し、呼んだ側の物を空にしない
        if isinstance(test, unittest.TestSuite):
            test = unittest.TestSuite(list(test))
        return super().run(test)


def paths(tier):
    """段のモジュールのファイル（works の根から。名前の順）。dev/tdd-suite.sh が pytest に渡す"""
    return sorted(f"{TESTS.name}/{m}.py" for m in tier_modules(tier))


def main(argv):
    if len(argv) >= 2 and argv[1] == "paths":
        if len(argv) != 3 or argv[2] not in TIERS:
            print("tiers: 使い方: python3 tests/tiers.py paths <fast|heavy>", file=sys.stderr)
            return 2
        bad = problems()
        if bad:
            print("tiers: " + " / ".join(bad), file=sys.stderr)
            return 2
        print("\n".join(paths(argv[2])))
        return 0
    listing = len(argv) >= 2 and argv[1] == "list"
    if listing:
        argv = argv[1:]
    if len(argv) < 2 or argv[1] not in (*TIERS, "all"):
        print("tiers: 段は fast・heavy・all（使い方: python3 tests/tiers.py [list] <段> [unittest の引数]）", file=sys.stderr)
        return 2
    try:
        shard = shard_env(os.environ)
    except ValueError as e:
        print(f"tiers: {e}", file=sys.stderr)
        return 2
    # 中の試験が起こす run.sh・tiers.py に組を継がせない（継ぐと中の一式が組の分だけになる）
    os.environ.pop("WORKS_SHARD", None)
    if argv[1] != "all":
        bad = problems()
        if bad:
            print("tiers: " + " / ".join(bad), file=sys.stderr)
            return 2
    keep = set(modules()) if argv[1] == "all" else tier_modules(argv[1])
    if shard is not None:
        index, total = shard
        # 組は段に依らず全部のモジュールで分ける（段ごとに分けると、同じ組の番号が段で別のモジュールを指す）
        keep &= set(shard_of(modules(), total)[index])
        print(f"tiers: 組 {index}/{total}（{len(keep)} 本のモジュール）", file=sys.stderr)
    if listing:
        print("\n".join(sorted(keep)))
        return 0
    loader = unittest.TestLoader() if argv[1] == "all" and shard is None else TierLoader(keep)
    # `python3 -m unittest` と同じ sys.path の頭（作業フォルダ）にする。tests/ は discover が頭に足す
    sys.path[0] = os.getcwd()
    unittest.main(module=None, testLoader=loader, testRunner=SkipGateRunner,
                  argv=["python -m unittest", "discover", "-s", str(TESTS), "-p", PATTERN, *argv[2:]])
    return 0  # unittest.main が終了コードで抜けるので、ここには来ない


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))
