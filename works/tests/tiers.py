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

並べ（WORKS_JOBS）: fast は子のプロセス（`tiers.py child <段> [unittest の引数]`）を並べる数だけ起こし、モジュールを重さの目安の
重い順に、手の空いた子へ 1 本ずつ渡す（モジュールは割らない）。子の結果（件数・失敗・見送り・モジュールごとの秒）は親が 1 つに
合わせ、見送りの門も合わせた一覧に 1 回当てて、1 本の時と同じ形と終了コードで出す。結果を返さずに終わった子は、回していた
モジュールを名指しして error に数える。並べる数の決め（jobs）は: WORKS_JOBS（1 以上の整数。1 なら今までどおり 1 本）、無ければ
CPU の数までで、いちばん重いモジュールの 1 本が律速になる所まで。heavy と全部は並べない（重いテストの枠の 1 本の中で回る）。
`python3 tests/tiers.py jobs <段>` は並べる数を出すだけ（dev/tdd-suite.sh が同じ数で pytest を並べる。決めを写さない）。
子の標準入力と標準出力は親との線で、子の試験の標準出力は標準エラーに寄せる（子ごとにまとめて、子が終わった順に写す）。
-f は子ごとに効く。並べた子は段のモジュールだけを import する（1 本の時は discover が全部を import するので、段の外の
モジュールの読み込みの失敗も error に出る。並べた時は出ない）。並べた時のモジュールごとの秒には、子の中のモジュールの読み込みと
並べた負荷の分が入る（重さの記録 shard-seconds.json は CI の行から取る）。

heavy に置く物: 試験ごとに git のリポジトリを作る（git init・commit・mktarget・dogfood の clone）・uv run を起こす・
Archon を起こす・golden を再生する・プロセスの木を起こす・決まった秒を待つ。短くても、これらを使うモジュールは heavy に置く
（負荷の高い機械では git と子のプロセスが遅れの元になる）。種の git を tests/gitkit.py の型（プロセスに 1 回だけ作る）の
写しで配るだけなら、試験ごとに作るに当たらない。段は使う物の形で分ける（決まっていて、読めば確かめられる）。
fast は秒の上限ではない（負荷の高い機械では fast の中の git・子のプロセスも遅れる）。
"""
import importlib
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import traceback
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
    "test_nodemeta",        # 節ごとの読み書きの宣言の形・YAML から落とす口・照らし・測る道具（YAML と manifest を読む・子のプロセスは python3 1 本。git なし）
    "test_gitkit",          # gitkit の型を 1 回作って 2 回写す
    "test_unittrees",       # 単位の worktree（種の git は gitkit の型の写し。試験ごとに worktree を 2〜3 本切る・子のプロセスは git だけ）
    "test_tdd_lane_wiring", # TDD の輪の並べの節の配線（YAML・筋書き・状態の JSON を読むだけ。git・子のプロセスなし）
    "test_fix_lane_wiring", # 修正役の並べの節の配線と並べの枝の部品の純粋な口（YAML・筋書き・表を読むだけ。git・盤面・子のプロセスなし）
    "test_lanekit",         # 並べの枝の部品の純粋な口と枝の数の写しの縛り（一時の置き場のファイル 1 つ・表を読むだけ。git・子のプロセスなし）
    "test_unitlanes",       # 下請けを単位の worktree で並べる（種の git は gitkit の型の写し。試験ごとに worktree を 2〜3 本切る・子のプロセスは git と python3 1 本）
    "test_blk_eyes_lanes",  # 独立の目の筋の順: YAML と Archon の trigger_rule の写しで節を回す（盤面の fixture を読むだけ。git・子のプロセスを使わない）
    "test_layers",          # 層と依存の向き（裁定 R59）: pack のファイルと YAML を読むだけ
    "test_block_blind",     # ブロックの散文のほかのブロックの名指しの柵と、役の指示書のほかの役・段の語の柵: git ls-files と追跡されたファイルを読むだけ（子のプロセスは git だけ）
    "test_concepthome",     # 判断の 1 軸と考えの住処の観点の文（文字列と名前の一覧だけ。git は差し替える）
    "test_concept_change",  # 柵を対象の変更に当てる口（種の git は gitkit の型の写し・子のプロセスは git だけ）
    "test_gatepolicy",      # 人の関所と無人の方針の住処の語・確かめ・読み・開くかの決め（一時の置き場のファイルだけ。git・子のプロセスなし）
    "test_startrec",        # 始めの記録の住処の読み口と入口の文（一時の置き場のファイルだけ。git・子のプロセスなし）
    "test_entry_block",     # 入口のブロックの置き場と約束（YAML と JSON を読むだけ。git・子のプロセスなし）
    "test_copy_fence",      # 写しの柵（表 docs/copies.json）: git ls-files と追跡されたファイルを読むだけ（子のプロセスは git だけ）
    "test_concept_fences",  # 考えの住処の柵（地図 docs/concepts.md と表 docs/concepts.json）: git ls-files と追跡されたファイルを読むだけ（子のプロセスは git だけ）
    "test_impact",          # 変更の周りの地図: 種の git は gitkit の型の写し・git ls-files と diff を読む（子のプロセスは git だけ）
    "test_halt",            # 線 A: 止め札を一時の盤面に置く・stop.sh を偽の Archon（sh の台本）で起こす・python を 8 本同時に起こす（git・uv・木なし）
    "test_node_marker",     # 線 A: 印の文字列を組んで読むだけ
    "test_gh_port",         # 役が読むだけの gh を呼ぶ形の柵: 指示書の md と YAML を読むだけ（git・子のプロセスなし）
    "test_forge",           # forge の無い remote の決め（forge.py）と盤面への差し替え・報告の 1 行・ghreads の条件外: 関数を直に呼ぶ・偽の盤面・git init と remote add・偽の gh（盤面・子の実行器なし）
    "test_gate_na",         # ゲートの検算の役の『条件外』の差し替えとゲートの印: 関数を直に呼ぶ・偽の盤面・一時の置き場に差分のファイル（git・盤面・子のプロセスなし）
    "test_hostgh",          # run の中で利用者の gh を継ぐ口（dev/hostgh.py）: 関数を直に呼ぶ・偽の gh と sh の口を子で起こすだけ（git・盤面なし）
    "test_carry_ci",        # run の後の CI の赤を次の依頼の prior_failures へ（carry.carry_ci）: 関数を直に呼ぶ・carry.py を python3 -I で起こすだけ（git・盤面なし）
    "test_chain",           # 周の鎖の住処（chain.py）: 関数を直に呼ぶ・一時の置き場のファイル・chain.main の口（git・Archon・子のプロセスなし）
    "test_carry_home",      # 次の run への持ち越しの住処（carry.py）: 関数を直に呼ぶ・一時の置き場のファイル・柵の表を読む（子のプロセスは git ls-files だけ）
    "test_stopby",          # 止めの理由の住処（stopby.py）: 関数を直に呼ぶ・pack の .py を ast で読む・柵の表を読む（子のプロセスは git ls-files だけ）
    "test_depth",           # 単位ごとの深さ（darkfactory/lib/depth.py）: 関数を直に呼ぶ・一時の置き場に書くだけ（盤面・git・子のプロセスなし）
    "test_cite",            # 名指しの形の住処（cite.py）: 関数を直に呼ぶだけ（git・子のプロセスなし）
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
    "test_webget",          # web の取得と run をまたぐ控え: 一時の置き場のファイルと転送の口を直に呼ぶだけ（網・git・子のプロセスなし）
    "test_world_check",     # 世界の解の抜き書きの照らしと検索語の検査: 関数を直に呼び、網の口は偽の get（網・git・子のプロセスなし）
    "test_worldmark",       # 世界の解の行の住処（worldmark）: 関数を直に呼ぶ・一時の置き場のファイルと約束の Schema を読むだけ（網・git・子のプロセスなし）
    "test_blk_world",       # 世界の解のブロック: 関数を直に呼ぶ・一時の置き場のファイル・節の口を python で子に 8 本（網・git・uv・Archon なし）
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
    "test_stubfold",        # 筋書きの共通の基の合わせ方（dev/stubfold.py）: テキストと YAML を読む・一時の置き場に写すだけ（子のプロセスは git show・log だけ）
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
    "test_graphmap",        # 工程の地図と包みの差し込みの表: 種の YAML と地図の元を読む・adapter.plan を直に呼ぶ・CLI を python3 で子で 6 本（git なし）
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


def jobs(environ, names, cpus):
    """並べる子のプロセスの数。WORKS_JOBS（1 以上の整数）が在ればその値、形が違えば ValueError。無ければ CPU の数（cpus）までで、
    組（shard_of）のいちばん重い組がいちばん重いモジュールの 1 本に並ぶ最小の数（それより増やしても律速の 1 本は縮まない）"""
    raw = environ.get("WORKS_JOBS", "")
    if raw != "":
        if not re.fullmatch(r"[1-9][0-9]*", raw):
            raise ValueError(f"WORKS_JOBS は 1 以上の整数（1 で並べない）（今の値: {raw}）")
        return int(raw)
    names = sorted(names)
    heaviest = max((weight(m) for m in names), default=0.0)
    for n in range(1, max(1, cpus)):
        if max(sum(weight(m) for m in g) for g in shard_of(names, n).values()) <= heaviest:
            return n
    return max(1, cpus)


def tier_jobs(tier, names, environ):
    """段を並べる数。並べるのは fast だけ（heavy と全部は機械全体の重いテストの枠の 1 本の中で回るので 1 本のまま）"""
    cpus = getattr(os, "process_cpu_count", os.cpu_count)() or 1
    n = jobs(environ, names, cpus)   # 形の確かめは段に依らない
    return n if tier == "fast" else 1


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


# 並べた子（`tiers.py child <段> [unittest の引数]`）と親の線: 親は子の標準入力にモジュールの名を 1 行ずつ渡し、子は回し終えるごとに
# 標準出力に JOB_READY の 1 行、入力が尽きたら JOB_RESULT の 1 行（結果の JSON）を返す。子の試験の出力は標準エラーに寄せる
JOB_READY = "tiers-job-ready"
JOB_RESULT = "tiers-job-result: "


class _Done:
    """子で回った試験の写し（親の SkipGateResult が id と説明の行を引く分だけ）"""

    def __init__(self, ident, text, short):
        self._id, self._text, self._short = ident, text, short

    def id(self):
        return self._id

    def __str__(self):
        return self._text

    def shortDescription(self):
        return self._short


def _done(test):
    return [test.id(), str(test), test.shortDescription()]


class _Muted:
    """書きを止められる流れ（子は結果を親へ返した後の Ran と OK の行を出さない。出すのは親）"""

    def __init__(self, stream):
        self._stream = stream
        self.on = True

    def write(self, text):
        if self.on:
            self._stream.write(text)

    def writeln(self, text=""):
        if self.on:
            self._stream.writeln(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _take_line():
    """子の標準入力と標準出力を親との線に取り、試験には標準入力に空・標準出力に標準エラーを当てる（試験とその子が線を読み書き
    しない。写した fd は子のプロセスに継がれない）。(読む口, 書く口)"""
    sys.stdout.flush()
    rin = os.fdopen(os.dup(0), "r", encoding="utf-8")
    wout = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    os.dup2(2, 1)
    return rin, wout


class JobQueue:
    """子の一式: 親から届くモジュールの名ごとに、その試験を読んで回し、JOB_READY を返す"""

    def __init__(self, loader, line):
        self.loader, (self.rin, self.wout) = loader, line

    def __call__(self, result):
        for name in self.rin:
            name = name.strip()
            if name:
                self.load(name)(result)
            self.wout.write(JOB_READY + "\n")

    def load(self, name):
        """discover と同じ読み方: 読み込みの SkipTest はモジュールごとの見送り、ほかの例外は読み込みの失敗の 1 件"""
        try:
            module = importlib.import_module(name)
        except unittest.SkipTest as e:
            return unittest.loader._make_skipped_test(name, e, self.loader.suiteClass)
        except Exception:
            return unittest.loader._make_failed_import_test(name, self.loader.suiteClass)[0]
        return self.loader.loadTestsFromModule(module, pattern=PATTERN)


class JobLoader(unittest.TestLoader):
    """子の discover: 名を読まずに JobQueue を返す（-k は unittest.main がこの loader に立て、loadTestsFromName が当てる）"""

    def discover(self, start_dir, pattern="test*.py", top_level_dir=None):
        sys.path.insert(0, str(TESTS))   # discover と同じく tests/ を import の頭に足す
        return JobQueue(self, _take_line())


class JobResult(SkipGateResult):
    """子の結果。見送りの門と一覧・失敗の本文は出さず、全部を親へ返す（親がまとめて 1 本の時と同じ形で出す）"""

    def printErrors(self):
        doc = {"run": self.testsRun,
               "errors": [[*_done(t), e] for t, e in self.errors],
               "failures": [[*_done(t), e] for t, e in self.failures],
               "skipped": [[*_done(t), r] for t, r in self.skipped],
               "expectedFailures": [[*_done(t), e] for t, e in self.expectedFailures],
               "unexpectedSuccesses": [_done(t) for t in self.unexpectedSuccesses],
               "secs": getattr(self, "_works_secs", {}),
               "durations": list(getattr(self, "collectedDurations", []))}
        self.stream.flush()
        sys.stdout.flush()
        wout = self._works_line
        wout.write(JOB_RESULT + json.dumps(doc, ensure_ascii=True) + "\n")
        wout.flush()
        self.stream.on = False


class JobRunner(SkipGateRunner):
    resultclass = JobResult

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream = _Muted(self.stream)

    def run(self, test):
        self._works_line = test.wout
        return super().run(test)

    def _makeResult(self):
        result = super()._makeResult()
        result._works_line = self._works_line
        return result


class Jobs:
    """子のプロセス（`tiers.py child <段> [unittest の引数]`）を workers 本起こし、モジュールを重い順に、手の空いた子へ 1 本ずつ渡す。
    子の結果は親の result に足し、子の出力は子が終わった順に子ごとにまとめて標準エラーへ写す。結果を返さずに終わった子は、
    回していたモジュールを名指しして error に数え、渡せずに残ったモジュールも error に数える"""

    def __init__(self, tier, names, workers, args):
        self.tier, self.workers, self.args = tier, workers, args
        self.todo = sorted(names, key=lambda m: (-weight(m), m))

    def __call__(self, result):
        lock = threading.Lock()
        todo = list(self.todo)
        procs = []

        def work():
            try:
                with subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), "child", self.tier,
                                       *self.args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8", errors="replace") as p:
                    with lock:
                        procs.append(p)
                    doing, rest, err = self._drive(p, lock, todo)
                with lock:
                    sys.stderr.write(err)
                    sys.stderr.flush()
                    self._take(result, p.returncode, doing, rest)
            except BaseException:   # 線の読み書き・結果の読みの思わぬ例外も黙らせない（流れの外の糸では投げても消える）
                with lock:
                    result.errors.append((_Done("tiers.job", "子のプロセスの扱い", None), traceback.format_exc()))

        threads = [threading.Thread(target=work) for _ in range(min(self.workers, len(todo)))]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            with lock:
                stopped = bool(todo) and any(t.is_alive() for t in threads)
                if stopped:
                    todo.clear()   # 止められた（Ctrl-C など）: 残りを渡さない
                for p in procs:
                    if p.poll() is None:
                        p.kill()
        if todo:
            result.errors.append((_Done("tiers.job", "子のプロセス", None),
                                  "子のプロセスが全部終わり、回らなかったモジュールが残った: " + ", ".join(todo)))

    @staticmethod
    def _drive(p, lock, todo):
        """子にモジュールを 1 本ずつ渡し、尽きたら線を閉じて結果を読む。(回していたモジュール（終えたなら None）, 結果の線の残り,
        標準エラー)。子の標準エラーは別の糸で読み、子が終わった後は残った孫が持ち続けても長くは待たない"""
        err = []
        reader = threading.Thread(target=lambda: err.extend(iter(lambda: os.read(p.stderr.fileno(), 65536), b"")),
                                  daemon=True)
        reader.start()
        doing, rest = None, ""
        try:
            while True:
                with lock:
                    doing = todo.pop(0) if todo else None
                if doing is None:
                    break
                p.stdin.write(doing + "\n")
                p.stdin.flush()
                if p.stdout.readline() != JOB_READY + "\n":
                    break
                doing = None
            p.stdin.close()
            rest = p.stdout.read()
        except OSError:   # 子が先に終わって線が切れた
            pass
        p.wait()
        reader.join(timeout=10)
        return doing, rest, b"".join(err).decode("utf-8", "replace")

    @staticmethod
    def _take(result, rc, doing, rest):
        doc = None
        for line in rest.splitlines():
            if line.startswith(JOB_RESULT):
                try:
                    doc = json.loads(line[len(JOB_RESULT):])
                except ValueError:   # 書く途中で切れた行は、結果が無いのと同じに数える
                    doc = None
        if doing is not None or doc is None or rc not in (0, 1, 5):
            what = f" {doing} を回す間に" if doing is not None else ""
            result.errors.append((_Done("tiers.job", f"子のプロセス（{doing or '結果'}）", None),
                                  f"子のプロセスが{what}結果を返さずに終わった（終了コード {rc}）" if doc is None
                                  else f"子のプロセスが{what}終了コード {rc} で終わった"))
        if doc is None:
            return
        result.testsRun += doc["run"]
        for key in ("errors", "failures", "skipped", "expectedFailures"):
            getattr(result, key).extend((_Done(*t[:3]), t[3]) for t in doc[key])
        result.unexpectedSuccesses.extend(_Done(*t) for t in doc["unexpectedSuccesses"])
        secs = getattr(result, "_works_secs", None)
        if secs is None:
            secs = result._works_secs = {}
        for m, v in doc["secs"].items():
            secs[m] = secs.get(m, 0.0) + v
        if hasattr(result, "collectedDurations"):
            result.collectedDurations.extend(tuple(d) for d in doc["durations"])


class JobsLoader(unittest.TestLoader):
    """親の discover: Jobs を返す（-k などの引数は unittest.main が親で読み、子にもそのまま渡す）"""

    def __init__(self, jobs_):
        super().__init__()
        self.jobs = jobs_

    def discover(self, start_dir, pattern="test*.py", top_level_dir=None):
        return self.jobs


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
    listing = len(argv) >= 2 and argv[1] in ("list", "jobs")
    if listing:
        listing, argv = argv[1], argv[1:]
    # 並べた子: `tiers.py child <段> [unittest の引数]`。親（Jobs）が起こし、線で渡されたモジュールを回して結果を返す
    job = len(argv) >= 3 and argv[1] == "child"
    if job:
        argv = argv[1:]
    if len(argv) < 2 or argv[1] not in (*TIERS, "all"):
        print("tiers: 段は fast・heavy・all（使い方: python3 tests/tiers.py [list|jobs] <段> [unittest の引数]）", file=sys.stderr)
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
    if listing == "list":
        print("\n".join(sorted(keep)))
        return 0
    try:
        n = 1 if job else tier_jobs(argv[1], keep, os.environ)
    except ValueError as e:
        print(f"tiers: {e}", file=sys.stderr)
        return 2
    if listing == "jobs":
        print(n)
        return 0
    runner = SkipGateRunner
    if job:
        loader, runner = JobLoader(), JobRunner
    elif n > 1:
        loader = JobsLoader(Jobs(argv[1], keep, n, argv[2:]))
    else:
        loader = unittest.TestLoader() if argv[1] == "all" and shard is None else TierLoader(keep)
    # `python3 -m unittest` と同じ sys.path の頭（作業フォルダ）にする。tests/ は discover が頭に足す
    sys.path[0] = os.getcwd()
    unittest.main(module=None, testLoader=loader, testRunner=runner,
                  argv=["python -m unittest", "discover", "-s", str(TESTS), "-p", PATTERN, *argv[2:]])
    return 0  # unittest.main が終了コードで抜けるので、ここには来ない


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))
