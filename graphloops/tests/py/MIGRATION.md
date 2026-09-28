# bash の台本から pytest への移し替えの対応表

graphloops/tests/simulate.py・simulate_review.py（bash の tests/run.sh が束ねる台本）の検査を、このディレクトリの pytest へ段ごとに移した記録。段の名前（S2b ほか）はリポジトリの外の計画 testplan/PLAN.md の段。移すときの決まりは [README の「pytest の置き場」](../../README.md#pytest-の置き場graphloopstestspy)。

- 台本の check 1 件をテスト 1 件（parametrize の 1 行か 1 関数）に写す。件数の柵（conftest.py の EXPECTED_ITEMS）が check の粒度で数え続け、落ちた検査が 1 件ずつ並ぶ
- 盤面を端から端まで回す筋書きは、本文を台本の check のまま移し、土台の gl_script で台本のモジュールを借りる。件数は EXPECTED_SIM_CHECKS が数える
- 途中の盤面に 1 手を当てて確かめる検査（否定検査など）は、控えた波・1 手・手で書いた期待（assert）の形に移す（T1）。波は waves.py が台本の前半を同じプロセスで 1 度だけ回して控え、検査ごとに控えから始める。台本の check は数えない（EXPECTED_SIM_CHECKS は動かない）。行き先は各テストの印 `moved_from` が名乗り、台帳（ledger.py）が台本の check ごとに機械で組む——空欄と、名乗りが check にちょうど 1 件で当たらない物と、下の表の古びは test_ledger.py が赤にする
- 元の文言は、移した先のテストの名前・docstring・コメントと、下の表の 1 行で運ぶ。表の「元の check」は台本が出していた行の頭（描画した値は元の回の物）

## S2b（2026-09-27）

simulate.py の small 8 本と、research の標準の収束（e2e）1 本を移し、bash 側を消した。schema の検査は S2a で pytest 側に写しを作ってあった物を正本にし、写しが落としていた拒む綴り 2 つ（engine#/$defs/a・#/xxxxxxa）を戻した。

| 元の台本の関数 | check の数 | 移した先 |
|---|---|---|
| test_units | 13 | test_engine_parts.py（描画・上限の 6）と test_schema.py（型検査の 7） |
| test_schema_pattern_properties | 4 | test_schema.py |
| test_schema_end_anchored | 9 | test_schema.py |
| test_schema_refs_fail_closed | 9 | test_schema.py（#/<engine の表の名前> だけ test_schema_boundaries.py） |
| test_parse_output | 21 | test_engine_parts.py |
| test_set_path | 17 | test_engine_parts.py |
| test_threshold_boundaries | 6 | test_research_rules.py（①②の 4）と test_engine_parts.py（③の 2） |
| test_cond_truth_tables | 21 | test_research_rules.py |
| test_converges | 23 | test_sim_research.py（台本の check のまま。件数は EXPECTED_SIM_CHECKS） |

件数の定数: graphloops/tests/run.sh の EXPECTED_CHECKS 2018 → 1895（simulate.py が 832 → 709 件）・EXPECTED_TESTS 164 → 155、conftest.py の EXPECTED_ITEMS 882 → 956・EXPECTED_SIM_CHECKS 5 → 28。

### 変異の腕

移した関数だけを当てにしていた腕 7 本は、tests/mutate.py がまだ pytest を回せないので、腕の中身ごと tests/mutations.json の dropped に移した（理由と戻す条件は各行の why、殺すはずのテストは kill_by）。wip/mut-pytest（mutate.py に pytest の口を足す変更）が入った時点で arms へ戻す。**この段の変更は、その変更と同じ版か、その後にしか main に入れない。** 旧の側（bash の台本）でも新の側でも撃っていない——未撃ち（合流後 CI。人の方針: 変異は手元で撃たない）。

| 腕 | 殺すはずのテスト |
|---|---|
| e13 | graphloops/tests/py/test_schema.py::test_types[maxLength-over] |
| e14 | graphloops/tests/py/test_schema.py::test_types[maxLength-counts-spaces] |
| S01 | graphloops/tests/py/test_schema.py::test_pattern_properties_checks_value_type |
| SC1 | graphloops/tests/py/test_schema.py::test_end_anchored[escaped-open-bracket-then-close] |
| SC2 | graphloops/tests/py/test_schema.py::test_end_anchored[bracket-first-in-negated-class] |
| SC3 | graphloops/tests/py/test_schema.py::test_unexpanded_ref_is_rejected |
| SC4 | graphloops/tests/py/test_schema.py::test_ref_outside_the_two_spellings_is_rejected[engine-defs-engine-name] |

移した関数を tests に持つ腕と、expect の頭が消した check の文言に当たる腕は、上の 7 本だけ（tests/mutate.py --check が消した後の版で通ることで確かめた）。

### check ごとの対応

#### test_units

| 元の check | 移した先 |
|---|---|
| reads に在る穴は埋まる | test_engine_parts.py::test_reads_hole_is_filled |
| reads に無い穴は optional でも ReadsViolation（KeyError… | test_engine_parts.py::test_hole_outside_reads_raises_even_when_optional |
| reads の中の『無い』穴は optional なら語で埋まる（空にしない） | test_engine_parts.py::test_missing_optional_hole_is_filled_with_a_word |
| 文の途中でも語が残る（読む側が真偽を決められる） | test_engine_parts.py::test_missing_optional_hole_mid_sentence_keeps_the_word |
| 上限はバイトで効く（20000 字＝60000 バイトを切った） | test_engine_parts.py::test_cap_is_in_bytes |
| 上限内はそのまま | test_engine_parts.py::test_under_cap_is_unchanged |
| enum: True は語彙 [0, 1] に無い（bool は int の部分型） | test_schema.py::test_types[enum-true-is-not-1] |
| enum: 1 は通る | test_schema.py::test_types[enum-1-passes] |
| const: True は 1 でない | test_schema.py::test_types[const-true-is-not-1] |
| minLength: 空白だけは空と数える | test_schema.py::test_types[minLength-strips-spaces] |
| maxLength: 上限を超えた字列は落とす | test_schema.py::test_types[maxLength-over] |
| maxLength: ちょうどは通る | test_schema.py::test_types[maxLength-exact] |
| maxLength: 前後の空白も数える（削って測らない） | test_schema.py::test_types[maxLength-counts-spaces] |

#### test_schema_pattern_properties

| 元の check | 移した先 |
|---|---|
| patternProperties: 形に合う名前は受ける | test_schema.py::test_pattern_properties_accepts_matching_name |
| patternProperties: 形に合わない名前は additionalProperti… | test_schema.py::test_pattern_properties_other_name_goes_to_additional |
| patternProperties: 形に合う名前も値の型は見る | test_schema.py::test_pattern_properties_checks_value_type |
| patternProperties: 中の語も engine の読む語かを見る | test_schema.py::test_pattern_properties_keywords_are_walked |

#### test_schema_end_anchored

| 元の check | 移した先 |
|---|---|
| pattern: $ は末尾の改行の手前で一致しない（Python の $ と違う） | test_schema.py::test_end_anchored[dollar-not-before-final-newline] |
| pattern: \$ はエスケープした字のまま（\Z に読み替えない） | test_schema.py::test_end_anchored[escaped-dollar-stays] |
| pattern: 文字クラスの中の $ は字のまま | test_schema.py::test_end_anchored[dollar-in-class-stays] |
| pattern: 文字クラスは ] まで続く（2 字目以降の後の $ もクラスの中） | test_schema.py::test_end_anchored[class-runs-to-bracket] |
| pattern: [ の直後の ] は文字クラスの中の字で、その後の $ もクラスの中 | test_schema.py::test_end_anchored[bracket-first-in-class] |
| pattern: 文字クラスを閉じた後の $ は末尾 | test_schema.py::test_end_anchored[dollar-after-class] |
| pattern: エスケープした [ の直後の ] はクラスを閉じ、後ろの $ は末尾 | test_schema.py::test_end_anchored[escaped-open-bracket-then-close] |
| pattern: [^ の直後の ] はクラスの中の字（コンパイルでき、$ もクラスの中） | test_schema.py::test_end_anchored[bracket-first-in-negated-class] |
| pattern: [^] の後のクラスを閉じた $ は末尾 | test_schema.py::test_end_anchored[dollar-after-negated-class] |

#### test_schema_refs_fail_closed

| 元の check | 移した先 |
|---|---|
| 未展開の $ref は何でも通すのでなく拒む | test_schema.py::test_unexpanded_ref_is_rejected |
| engine#/<名前> は引ける | test_schema.py::test_engine_ref_resolves |
| #/$defs/<名前> は引ける | test_schema.py::test_local_ref_resolves |
| engine#/$defs/count_how は名乗りの外なので拒む（$ref 'engin… | test_schema.py::test_ref_outside_the_two_spellings_is_rejected[engine-defs-engine-name] |
| engine#/$defs/a は名乗りの外なので拒む（$ref 'engine#/$defs… | test_schema.py::test_ref_outside_the_two_spellings_is_rejected[engine-defs-local-name] |
| #/a は名乗りの外なので拒む（$ref '#/a' が引けない（引けるのは #/$defs/… | test_schema.py::test_ref_outside_the_two_spellings_is_rejected[local-without-defs] |
| #/xxxxxxa は名乗りの外なので拒む（$ref '#/xxxxxxa' が引けない（引け… | test_schema.py::test_ref_outside_the_two_spellings_is_rejected[local-six-chars-then-local-name] |
| #/count_how は名乗りの外なので拒む（$ref '#/count_how' が引けな… | test_schema_boundaries.py::test_ref_mixed_spellings_are_rejected[local-source-with-engine-name] |
| other#/a は名乗りの外なので拒む（$ref 'other#/a' が引けない（引けるの… | test_schema.py::test_ref_outside_the_two_spellings_is_rejected[other-source] |

#### test_parse_output

| 元の check | 移した先 |
|---|---|
| 本文に ``` を含む素の JSON は、そのまま読める（囲いと誤認しない） | test_engine_parts.py::test_bare_json_with_fences_inside_reads_as_is |
| 全体を ```json で囲った返答は剥がして読める | test_engine_parts.py::test_whole_reply_in_json_fence_is_unwrapped |
| 前後に文が付いた囲いも読める | test_engine_parts.py::test_fence_with_prose_around_is_read |
| JSON の無い返答は Reject | test_engine_parts.py::test_reply_without_json_is_rejected |
| 拒否の文が、試した相異なる候補の本数を言う | test_engine_parts.py::test_rejection_says_how_many_distinct_candidates_were_tried |
| 候補ごとに、どの切り方で何が起きたかを並べる | test_engine_parts.py::test_rejection_lists_what_each_cut_did |
| 折れた所として、実際に壊れている値が前後ごと出る | test_engine_parts.py::test_rejection_shows_the_broken_value_in_context |
| 診断行が、試した候補と同じ本数だけ並ぶ（原因を 1 本に畳まない。実際 2） | test_engine_parts.py::test_diagnostic_lines_match_candidates_tried |
| 同じ中身の候補を 2 回試さない（同一の診断行が並ばない） | test_engine_parts.py::test_same_candidate_is_not_tried_twice |
| 助言行が付く（役に直し方を教える側——診断だけ出して直し方を出さない形にしない） | test_engine_parts.py::test_rejection_carries_advice |
| 折れた所が先頭寄りなら、前側に省略記号を付けない | test_engine_parts.py::test_no_leading_ellipsis_when_break_is_near_the_start |
| 折れた所の後ろが尽きているなら、後側に省略記号を付けない | test_engine_parts.py::test_no_trailing_ellipsis_when_nothing_follows |
| 3 本目の候補のラベルが、実際にその切り方で落ちたときに出る | test_engine_parts.py::test_third_candidate_label_shows_when_it_is_the_cut_that_failed |
| JSON を 1 文字も返していない返答では、全文候補が頭から落ちたことが見える | test_engine_parts.py::test_prose_with_braces_shows_whole_text_failed_from_the_start |
| 空の返答は候補の話をせず、中身が無いことだけを言う（''） | test_engine_parts.py::test_empty_reply_says_only_that_it_is_empty[empty] |
| 空の返答の拒否文が、3 入口のどれか 1 つを読み元と決め打たない（''） | test_engine_parts.py::test_empty_reply_does_not_name_one_input[empty] |
| 空の返答は候補の話をせず、中身が無いことだけを言う（'   '） | test_engine_parts.py::test_empty_reply_says_only_that_it_is_empty[spaces] |
| 空の返答の拒否文が、3 入口のどれか 1 つを読み元と決め打たない（'   '） | test_engine_parts.py::test_empty_reply_does_not_name_one_input[spaces] |
| 空の返答は候補の話をせず、中身が無いことだけを言う（'\n\n'） | test_engine_parts.py::test_empty_reply_says_only_that_it_is_empty[newlines] |
| 空の返答の拒否文が、3 入口のどれか 1 つを読み元と決め打たない（'\n\n'） | test_engine_parts.py::test_empty_reply_does_not_name_one_input[newlines] |
| 閉じ ``` が無い返答が、入力長に対して線形で落ちる（1 秒未満） | test_engine_parts.py::test_unclosed_fence_fails_in_linear_time |

#### test_set_path

| 元の check | 移した先 |
|---|---|
| 配列の要素を点の添字で書き換えられる | test_engine_parts.py::test_set_path_writes_list_element_by_dotted_index |
| 配列の中の鍵まで辿って書ける | test_engine_parts.py::test_set_path_walks_into_list_element_keys |
| 書いた所を get_path が同じ綴りで読める（読み書きの綴りが揃う） | test_engine_parts.py::test_get_path_reads_what_set_path_wrote |
| 書けない綴り questions[1] は落ちる（黙って別の場所を作らない） | test_engine_parts.py::test_set_path_refuses_unwritable_spelling[questions[1]] |
| 書けない綴り questions.9 は落ちる（黙って別の場所を作らない） | test_engine_parts.py::test_set_path_refuses_unwritable_spelling[questions.9] |
| 書けない綴り questions.1.k.deep は落ちる（黙って別の場所を作らない） | test_engine_parts.py::test_set_path_refuses_unwritable_spelling[questions.1.k.deep] |
| 角括弧の綴りが、その名前の鍵として新設されていない | test_engine_parts.py::test_bracket_spelling_does_not_create_a_key |
| 既存の辞書の下に葉を 1 つ新設できる | test_engine_parts.py::test_set_path_creates_one_leaf_under_existing_dict |
| 点を含む鍵を最長一致で食い、隣に入れ子を作らない | test_engine_parts.py::test_set_path_eats_dotted_key_longest_first |
| 書いた所を get_path が同じ綴りで読める（点入りの鍵） | test_engine_parts.py::test_get_path_reads_dotted_key_set_path_wrote |
| 2 段以上の新設は落ちる（どちらの読みも成り立つ綴りを機械が選ばない） | test_engine_parts.py::test_set_path_refuses_creating_two_levels |
| 落ちた綴りが途中まで書き込まれていない | test_engine_parts.py::test_refused_two_level_spelling_writes_nothing |
| 消す口は点を含む鍵を最長一致で食って消す | test_engine_parts.py::test_del_path_eats_dotted_key_longest_first |
| 消せない綴り outputs.nope は落ちる（無い鍵・リストの要素・辿れない親） | test_engine_parts.py::test_del_path_refuses_undeletable_spelling[outputs.nope] |
| 消せない綴り questions.0 は落ちる（無い鍵・リストの要素・辿れない親） | test_engine_parts.py::test_del_path_refuses_undeletable_spelling[questions.0] |
| 消せない綴り a.b.nope.deep は落ちる（無い鍵・リストの要素・辿れない親） | test_engine_parts.py::test_del_path_refuses_undeletable_spelling[a.b.nope.deep] |
| 落ちた消しは何も消していない | test_engine_parts.py::test_refused_deletes_delete_nothing |

#### test_threshold_boundaries

| 元の check | 移した先 |
|---|---|
| 下限より 1 字短い行は標本に使えない（11 字） | test_research_rules.py::test_line_one_short_of_probe_min_is_not_usable |
| 下限ちょうどの行は標本に使える（12 字。>= と > の取り違えがここで出る） | test_research_rules.py::test_line_exactly_probe_min_is_usable |
| 射程の外がちょうど許容ぴったり（本文 120 字の 5%＝6 字）なら通る（None） | test_research_rules.py::test_outside_exactly_the_allowance_passes |
| 許容を 1 字超えたら不成立になり、外に残った量を字数で言う（> と >= の取り違えがここで… | test_research_rules.py::test_outside_one_over_the_allowance_fails_and_says_how_much |
| 上限ちょうどの項目は落とさない（1000 バイト・落とした欄 []。> と >= の取り違えが… | test_engine_parts.py::test_item_exactly_inline_limit_is_kept |
| 上限を 1 バイト超えた項目は落とす（15 バイト・落とした欄 ['v']） | test_engine_parts.py::test_item_one_byte_over_inline_limit_drops_the_field |

#### test_cond_truth_tables

| 元の check | 移した先 |
|---|---|
| constraints_self_written の行 0: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[constraints_self_written-row0] |
| constraints_self_written の行 1: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[constraints_self_written-row1] |
| constraints_self_written の行 2: 期待 True・実際 True | test_research_rules.py::test_cond_truth_table[constraints_self_written-row2] |
| constraints_self_written の行 3: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[constraints_self_written-row3] |
| constraints_self_written の行 4: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[constraints_self_written-row4] |
| generation_due の行 0: 期待 True・実際 True | test_research_rules.py::test_cond_truth_table[generation_due-row0] |
| generation_due の行 1: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[generation_due-row1] |
| generation_due の行 2: 期待 True・実際 True | test_research_rules.py::test_cond_truth_table[generation_due-row2] |
| generation_due の行 3: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[generation_due-row3] |
| no_new_discrepancies の行 0: 期待 True・実際 True | test_research_rules.py::test_cond_truth_table[no_new_discrepancies-row0] |
| no_new_discrepancies の行 1: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[no_new_discrepancies-row1] |
| no_new_discrepancies の行 2: 期待 die・実際 die | test_research_rules.py::test_cond_truth_table[no_new_discrepancies-row2] |
| rederiver_compare_due の行 0: 期待 True・実際 True | test_research_rules.py::test_cond_truth_table[rederiver_compare_due-row0] |
| rederiver_compare_due の行 1: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[rederiver_compare_due-row1] |
| rederiver_compare_due の行 2: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[rederiver_compare_due-row2] |
| rederiver_compare_due の行 3: 期待 die・実際 die | test_research_rules.py::test_cond_truth_table[rederiver_compare_due-row3] |
| sampling_due の行 0: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[sampling_due-row0] |
| sampling_due の行 1: 期待 True・実際 True | test_research_rules.py::test_cond_truth_table[sampling_due-row1] |
| sampling_due の行 2: 期待 False・実際 False | test_research_rules.py::test_cond_truth_table[sampling_due-row2] |
| sampling_due の行 3: 期待 die・実際 die | test_research_rules.py::test_cond_truth_table[sampling_due-row3] |
| CONDS の名前が全部真偽表に在る（表に無い: []） | test_research_rules.py::test_every_cond_has_a_truth_table |

#### test_converges

| 元の check | 移した先 |
|---|---|
| init が通る | test_sim_research.py::test_converges |
| p1.checker は mode=agent・engine が起こして材料は stdin（受… | test_sim_research.py::test_converges |
| 統合の節には記録の本文でなく置き場と要約が渡る | test_sim_research.py::test_converges |
| 統合の節には記録の本文でなく置き場と要約が渡る | test_sim_research.py::test_converges |
| p3.cold_reader は mode=cli・engine が起こして材料は stdin… | test_sim_research.py::test_converges |
| 統合の節には記録の本文でなく置き場と要約が渡る | test_sim_research.py::test_converges |
| status が converged | test_sim_research.py::test_converges |
| convergence が 3 周・連続 2: {'rounds_total': 3, 'co… | test_sim_research.py::test_converges |
| cold_reader が 2 周（redesign→pass） | test_sim_research.py::test_converges |
| rederiver は比較係の pass | test_sim_research.py::test_converges |
| 標準では cartographer は not_applicable | test_sim_research.py::test_converges |
| 抜き取りが走り覆り 0: {'status': 'done', 'sampled_ids': … | test_sim_research.py::test_converges |
| B は再照合で確証に戻った | test_sim_research.py::test_converges |
| 荷重の確証 A は反証を経た | test_sim_research.py::test_converges |
| 訂正の番号は機械が連番で振る: [1, 2] | test_sim_research.py::test_converges |
| report.md が保存された | test_sim_research.py::test_converges |
| 開いた問いの無い収束の文言は元のまま: ['連続 2 周で新規相違ゼロ、標準 段のゲートは全部… | test_sim_research.py::test_converges |
| 検証器が exit 0（機械で見つけられる発行の阻害は無い。**これは品質・飽和の宣言ではない… | test_sim_research.py::test_converges |
| 独立出典だけなので independence_review は na | test_sim_research.py::test_converges |
| refuter は A（荷重確証）と B（相違）に走った | test_sim_research.py::test_converges |
| 3 周目の checker は項目ゼロ（empty） | test_sim_research.py::test_converges |
| 省略なし | test_sim_research.py::test_converges |
| 標準・収束: 盤面の loop（['sampled_r2', 'sampled_r3', 's… | test_sim_research.py::test_converges |

## T1（2026-09-27）

否定検査 2 本（simulate_review.py と simulate.py の test_rejections）の check を、控えた波・1 手・手で書いた期待の pytest に移した。**台本はまだ消していない**——台本を消すのは、下の変異の腕の証明が CI で済んだ後の run（testplan の REDESIGN.md 4.2 の 4 条件）。それまでは同じ検査が両方に在り、片方を直したらもう片方も直す（ずれを見る柵は無い。waves.py の前半の手順の写しも同じ）。

| 元の台本の関数 | check の数 | 移した先 |
|---|---|---|
| simulate_review.py の test_rejections | 74 | test_rejections_review.py（74 件。すべて medium） |
| simulate.py の test_rejections | 43 | test_rejections_research.py（43 件。盤面を使う 36 件は medium、engine の部品とソースを直に見る 7 件は small） |

- **途中の盤面を作る口**（waves.py）: 台本の Run・answers・base_answers・settle を import して借り、glharness.driven(台本, "inproc") の下で前半を同じプロセスで回す（git は本物）。波ごとに Run の作業場（型のリポジトリ・盤面・設定）をまるごと控え、検査は同じ置き場へ控えを写し戻して始める（盤面の中の絶対パスを書き換えない）。控えは worker ごとの session の fixture で 1 度だけ作る。台本の test_rejections だけに在る前半の手順（主張 A を太らせる・stray.txt と --accept-tree-change・拒ませてから通す done）は waves.py に写してある
- **台帳**（ledger.py・test_ledger.py）: 台本の関数の中の check を ast で並べ、各テストの印 `moved_from(台本, 説明の頭, kept=通しに残す理由)` と突き合わせる。下の表は `python3 graphloops/tests/py/ledger.py` が刷った物
- **件数の定数**: conftest.py の EXPECTED_ITEMS 956 → 1078（+74・+43・台帳の柵 5）。graphloops/tests/run.sh の EXPECTED_CHECKS・EXPECTED_TESTS は台本を消していないので変えない。EXPECTED_SIM_CHECKS も変えない（新しい検査は台本の check を呼ばない）

### 通しに残す物

同じプロセスの検査では見えない物は、移した先のテストで中身を見た上で、台本（子プロセスで loop.py を起こす通し）にも残す。表の「通しに残す」の列が理由:

- loop.py record の子プロセスの標準出力と終了コード（台本が CLI の煙を置く唯一の所）
- PYTHONIOENCODING=cp1252 の下での標準入力の読み（起動時にだけ効く設定。3 OS の通しで windows-latest だけ赤だった腕）
- loop.py init の argv と、入口の拒否が 0 以外の終了コードになること（2 件）

### 被覆の包含（REDESIGN.md 4.2 の 4）

道具は cover_moved.py（手で撃つ。pytest の一式には入れない）。旧い側は台本 2 関数を glharness の inproc の口で 1 回ずつ回して測り（loop.py が同じプロセスに回るので engine の行が測れる。cli の口のまま測ると旧い側が部品の行だけになり、包含が恒真になる）、新しい側は移した先の 2 ファイルを pytest-cov の --cov-context=test で測った。波は --gl-prebuild-waves で最初のテストの準備（setup）に全部作らせ、検査の本体（run）と分けて数える。計測器は ctrace（Python 3.14 の既定の sysmon は動的な文脈を持たない）。測る行は graphloops/engine・rules・scripts。

2026-09-27 の測り（Python 3.14・coverage 7.16.1・pytest-cov 7.1.0・testslot の枠の中。旧い側は台本を 1 回回した控えを使い回した）:

| 物 | 全体 | review | research |
|---|---|---|---|
| 旧い側の行（うち engine） | 4,306（2,013） | 3,929（1,901） | 1,970（1,099） |
| 新しい検査の本体（run）が通した | 3,392 | 2,565 | 1,758 |
| 波の作り（setup）だけが通した | 719 | 1,169 | 212 |
| 読み込みだけ（集める段の import。文脈が空） | 195 | 195 | 0 |
| どこにも含まれない | 0 | 0 | 0 |
| 旧い側の行をそれだけが覆う新しいテスト（外すと包含が崩れる） | 49 本 | 38 本 | 16 本 |

- 波の作りだけが通した行は、台本の側でも前半の歩き（init・正しい done・next・走らせる節の launch）で通っていた行で、台本の check はそこを直に見ていない。前半が崩れたら、台本は例外で止まり、waves.py も例外で止まる（同じ強さ）。多いのは engine/commands.py・role_run.py・runner.py（launch）・rules の受け付けの正しい側・graphcheck.py（init が graph を確かめる）
- 読み込みだけの 195 行は、class の中の def・decorator など import の時に通る行（旧い側は台本の import ごと測った）
- review と research の列の和が全体と合わないのは、同じ engine の行を両方の台本が通るため

所要（同じ回）: 旧い側は inproc と ctrace の下で review 5.9 秒（74 件）・research 0.9 秒（43 件）。新しい側は 117 件を 1 プロセスで 18 秒前後（被覆つき）。被覆なしの 1 プロセスでは review 11.1 秒・research 4.0 秒——同じプロセスで回した台本より速くはない（1 件ごとに控えを写し戻し、1 手を打つため）。cli の口の台本の所要はこの run では測っていない（台本を回したのは被覆の 1 回だけ）。この段が変えたのは速さでなく、1 件ずつ独立に落ち、pytest-xdist で割れ、子の Python を起こさない形である。

### 変異の腕

tests/mutations.json で test_rejections を当てにする腕は 20 本。この run では腕を動かしていない（台本は残り、腕は今も台本で撃てる）。**撃つのは CI だけ**（人の方針）。腕の実行器 tests/mutate.py はまだ pytest を回せない（pytest の口は wip/mut-pytest が足す）ので、下の手順はその口が入ってから CI で撃つ:

1. 口が入った版で、下の腕を 1 本ずつ、tests に「移した先」の node id だけを書いて撃つ（台本は tests から外す）
2. Killed で、落ちたテストが「移した先」の node id なら、その腕の tests を node id に付け替えてよい。expect は腕の中身の文言のままで、新しいテストの失敗の文面に当たるかを見る（当たらなければ expect を新しいテストの assert の文面に替える）
3. Survived なら付け替えない。台帳の行に理由を書き、台本を消す run の前に新しいテストを足す
4. 20 本が全部付け替わり、前の変異の結果で台本 2 本が殺した自動の腕（REDESIGN.md 4.2 の 3）も新しいテストで殺せたら、台本 2 本を消す run の条件がそろう

| 腕 | 撃つファイル | expect（頭） | 元の check の行 | 殺すはずのテスト（移した先） |
|---|---|---|---|---|
| e08 | review-loop.py | 改行を含む cite は exit 1 | 1856 | test_rejections_review.py::test_fix_reply_is_rejected[cite-with-newline] |
| e20 | review-loop.json | wrote_refs を落とした返答は型で拒まれる | 1848 | test_rejections_review.py::test_fix_reply_is_rejected[wrote-refs-dropped] |
| f06 | review-loop.py | 改行を含む cite は exit 1 | 1856 | test_rejections_review.py::test_fix_reply_is_rejected[cite-with-newline] |
| m11 | review-loop.py | 残した理由を書けば部分的な覆いは通る | 1835 | test_rejections_review.py::test_fix_reply_is_rejected[partial-coverage-with-remaining] |
| K5a | review-loop.py | 修正前の母数 1・修正後に engine が数えた 0 が記録に残る | 1874 | test_rejections_review.py::test_coverage_before_and_after_are_recorded |
| K5b | review-loop.py | 修正前の母数 1・修正後に engine が数えた 0 が記録に残る | 1874 | test_rejections_review.py::test_coverage_before_and_after_are_recorded |
| K9 | review-loop.py | 判定者の書いた件数は engine が数えた件数に置き換わり、置き換えたことが | 1736 | test_rejections_review.py::test_judge_count_is_replaced_by_the_engine_count |
| P01 | validator.py | inspector は Read を持っても本文を貼る | 1597 | test_rejections_review.py::test_inspector_gets_pasted_body_and_investigator_gets_a_path |
| R06 | review-loop.py | 先行例: 直す単位の行が欠けた judge の返答は exit 1 | 1671 | test_rejections_review.py::test_judge_reply_is_rejected[precedent-row-missing] |
| R07 | review-loop.py | 先行例: 人へ回す問いに決まらない理由が無ければ exit 1 | 1686 | test_rejections_review.py::test_judge_reply_is_rejected[human-question-needs-undecided-because] |
| R08 | review-loop.py | 先行例: 修正の先行例に出典が無ければ exit 1 | 1808 | test_rejections_review.py::test_fix_reply_is_rejected[fix-precedent-without-source] |
| R13 | review-loop.py | リンク: 申告が空でも | 1828 | test_rejections_review.py::test_fix_reply_is_rejected[markdown-links-added-by-the-diff] |
| O01 | advance.py | 返答の置き場のディレクトリは engine が作る | 1572 | test_rejections_review.py::test_out_path_directories_are_made_by_the_engine |
| NF1 | review-loop.py | 先行例: 見つからないなら何を探したかが要る | 1676 | test_rejections_review.py::test_judge_reply_is_rejected[not-found-without-searched] |
| RN2 | review-loop.json | 順位（主経路）: 外部標準照合の done は | 1614 | test_rejections_review.py::test_external_standards_without_rankings_none_is_rejected |
| PD1 | review-loop.py | 先行例: 同じ key の行が 2 つある judge の返答は exit 1 | 1678 | test_rejections_review.py::test_judge_reply_is_rejected[precedent-key-duplicated] |
| PE1 | review-loop.py | 先行例: 人へ回す問い（escalate）にも先行例の行が要る | 1681 | test_rejections_review.py::test_judge_reply_is_rejected[escalate-needs-precedent] |
| NR1 | review-loop.py | 覆い: 判定者の母数より狭い how は理由なしで拒む | 1803 | test_rejections_review.py::test_fix_reply_is_rejected[how-narrower-than-judge] |
| BR1 | review-loop.py | 覆い: 空語（『なし』）の remaining は理由に数えない | 1805 | test_rejections_review.py::test_fix_reply_is_rejected[remaining-empty-word] |
| DG1 | advance.py | 任せ先: graph が delegate を宣言した回す側の節は | 1578 | test_rejections_review.py::test_undeclared_repo_falls_back_to_a_delegate |

### check ごとの対応

#### simulate_review.test_rejections

| 行 | 元の check（説明の頭） | 移した先 | 通しに残す |
|---|---|---|---|
| 1572 | 返答の置き場のディレクトリは engine が作る（最初の波の節も、運び手が mkdir せずに書ける） | test_rejections_review.py::test_out_path_directories_are_made_by_the_engine |  |
| 1574 | 宣言の在るリポジトリでは、走らせるだけの節は engine が走らせる節（mode=engine_run）で出て、任せ先… | test_rejections_review.py::test_declared_checks_run_as_an_engine_run_node |  |
| 1578 | 任せ先: graph が delegate を宣言した回す側の節は ready に任せ先が載り、宣言の無い節には載らない… | test_rejections_review.py::test_undeclared_repo_falls_back_to_a_delegate |  |
| 1585 | 実在しない BASE は exit 1 | test_rejections_review.py::test_nonexistent_base_is_rejected |  |
| 1590 | 機械の節（作業ツリーの写し）は ready に出ない | test_rejections_review.py::test_machine_nodes_are_not_ready |  |
| 1591 | loop.py record は record.json の丸写し（直読みと同じ値。CLI の煙テストはここ 1 か所） | test_rejections_review.py::test_record_command_copies_record_json | 子プロセスで起こした loop.py record の標準出力の文字コードと終了コード（台本が CLI の煙を置く唯一の所） |
| 1596 | P1 の役が同じ波に並ぶ:  | test_rejections_review.py::test_p1_roles_share_one_wave |  |
| 1597 | inspector は Read を持っても本文を貼る渡し方（ファイルの指示に従えの 1 文を拒むため）、investi… | test_rejections_review.py::test_inspector_gets_pasted_body_and_investigator_gets_a_path |  |
| 1602 | 今の周に走った節の素材が carried_over を名乗ると exit 1（rc= | test_rejections_review.py::test_material_of_a_node_that_ran_cannot_claim_carried_over |  |
| 1605 | cold-reader には観点の節と差分本文だけが貼られ、目的は貼られない | test_rejections_review.py::test_cold_reader_prompt_has_lens_and_diff_but_no_purpose |  |
| 1607 | found なのに count が無い素材は exit 1（検証器の表で先に見る） | test_rejections_review.py::test_found_material_without_count_is_rejected |  |
| 1611 | investigator の instance の前後で作業ツリーが変わると exit 1 | test_rejections_review.py::test_worktree_change_around_an_investigator_is_rejected |  |
| 1614 | 順位（主経路）: 外部標準照合の done は、空の順位を付けられない理由なしで拒む（ | test_rejections_review.py::test_external_standards_without_rankings_none_is_rejected |  |
| 1622 | cli で起こした遮断系の done に --agent-id を渡すと exit 1（engine が起こす節に Ag… | test_rejections_review.py::test_agent_id_on_a_cli_node_is_rejected |  |
| 1630 | 既に変更済みのファイルの中身を差し替えても止まる:  | test_rejections_review.py::test_replacing_content_of_an_already_modified_file_stops |  |
| 1635 | P1 の前後で作業ツリーが変わると先へ進まない | test_rejections_review.py::test_worktree_change_across_p1_stops |  |
| 1638 | 同じ止まり方で next を叩き直しても git_mismatches は増えない | test_rejections_review.py::test_repeated_next_on_the_same_stop_does_not_grow_git_mismatches |  |
| 1644 | git が無い場では P1 の前後の突合が『測れない』で止まる（一致に倒さない） | test_rejections_review.py::test_without_git_the_p1_comparison_stops_as_unmeasurable |  |
| 1650 | 自分の変更なら next --accept-tree-change で通る:  | test_rejections_review.py::test_accept_tree_change_passes_the_comparison |  |
| 1652 | 受け付けた理由が git_mismatches に残る | test_rejections_review.py::test_accepted_reason_is_kept_in_git_mismatches |  |
| 1661 | 受け付ければ judge に進み、素材は 15 欄で渡る | test_rejections_review.py::test_after_acceptance_the_judge_runs_with_materials |  |
| 1664 | 台帳の出どころが無い judge の返答は exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[origin-not-in-units] |  |
| 1667 | split の出どころが [block] の返答は exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[split-origin-is-block] |  |
| 1671 | 先行例: 直す単位の行が欠けた judge の返答は exit 1（ | test_rejections_review.py::test_judge_reply_is_rejected[precedent-row-missing] |  |
| 1674 | 先行例: 出典の無い行は exit 1（ | test_rejections_review.py::test_judge_reply_is_rejected[precedent-without-source] |  |
| 1676 | 先行例: 見つからないなら何を探したかが要る（ | test_rejections_review.py::test_judge_reply_is_rejected[not-found-without-searched] |  |
| 1678 | 先行例: 同じ key の行が 2 つある judge の返答は exit 1（ | test_rejections_review.py::test_judge_reply_is_rejected[precedent-key-duplicated] |  |
| 1681 | 先行例: 人へ回す問い（escalate）にも先行例の行が要る（ | test_rejections_review.py::test_judge_reply_is_rejected[escalate-needs-precedent] |  |
| 1686 | 先行例: 人へ回す問いに決まらない理由が無ければ exit 1（自明なので聞かない。 | test_rejections_review.py::test_judge_reply_is_rejected[human-question-needs-undecided-because] |  |
| 1689 | judge の label が語彙外（blocker）なら exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[label-outside-vocabulary] |  |
| 1691 | 台帳の kind が語彙外なら exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[kind-outside-vocabulary] |  |
| 1693 | disposition が語彙外なら exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[disposition-outside-vocabulary] |  |
| 1695 | 台帳の status が語彙外なら exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[status-outside-vocabulary] |  |
| 1697 | judge の返答に知らない欄があれば exit 1（additionalProperties） | test_rejections_review.py::test_judge_reply_is_rejected[unknown-field] |  |
| 1699 | defer に reason の無い judge の返答は exit 1（以前の台本は defer を一度も返さず、この… | test_rejections_review.py::test_judge_reply_is_rejected[defer-without-reason] |  |
| 1703 | 一撃が閉じると見込む unit を名指ししない judge の返答は exit 1（効かなかったことを次の周が言えない） | test_rejections_review.py::test_judge_reply_is_rejected[one-shot-closes-empty] |  |
| 1705 | one_shot_closes が今の周の units に無い key を指すと exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[one-shot-closes-unknown-key] |  |
| 1708 | [block] に class_query（母数の問い）が無い judge の返答は exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[block-without-class-query] |  |
| 1710 | class_query.total が数でなければ exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[class-query-total-not-a-number] |  |
| 1712 | 判定者の class_query も、走らせられない問いは exit 1（ | test_rejections_review.py::test_judge_reply_is_rejected[class-query-unrunnable] |  |
| 1718 | defer の単位には母数を求めない（赤の理由は key の重複だけ。 | test_rejections_review.py::test_judge_reply_is_rejected[defer-needs-no-class-query] |  |
| 1732 | 正しい judge の返答は通り、どこから読んだかが返事に残る（stdin を cp1252 の環境で。rc= | test_rejections_review.py::test_judge_reply_from_stdin_is_accepted_and_says_where_it_was_read | PYTHONIOENCODING=cp1252 は Python の起動時にだけ効く——同じプロセスでは、標準入力をバイトで読んで UTF-8 に決める経路をcp1252 の既定で試せない（3 OS の通しで windows-latest だけ赤だった実測の腕） |
| 1734 | 標準入力の返答が置き場の古い返答より優先され、記録に入るのは新しい方 | test_rejections_review.py::test_stdin_reply_wins_over_a_stale_out_path |  |
| 1736 | 判定者の書いた件数は engine が数えた件数に置き換わり、置き換えたことが note と返事に残る（ | test_rejections_review.py::test_judge_count_is_replaced_by_the_engine_count |  |
| 1739 | engine が 0 件を数えた単位は置き換えず、0 だったことが note と返事に残る（ | test_rejections_review.py::test_zero_engine_count_is_not_substituted |  |
| 1742 | engine が 0 件を数えた単位の key は、修正の側が読める値（engine_zero）にも残る（ | test_rejections_review.py::test_zero_count_unit_keys_are_left_for_the_fix |  |
| 1753 | [block] を直さない writer の返答は exit 1 で、残した理由を拒否文に併記する（ | test_rejections_review.py::test_fix_leaving_a_block_unfixed_is_rejected_with_its_reason |  |
| 1759 | 閉鎖の実証で赤を見ていないのに fix_closure=clean の返答は exit 1（rc= | test_rejections_review.py::test_clean_closure_without_red_seen_is_rejected |  |
| 1761 | 修正が在るのに fix_closure=not_applicable の返答は exit 1（changes が非空とい… | test_rejections_review.py::test_fix_reply_is_rejected[not-applicable-closure-with-changes] |  |
| 1764 | 2 つ以上の修正が触った面を書き落とすと exit 1（機械が files から面を出す） | test_rejections_review.py::test_fix_reply_is_rejected[interactions-left-out] |  |
| 1766 | 面ごとの修正の一覧（changes）は役に書かせない——書けば型で拒む（写しの入口を残さない） | test_rejections_review.py::test_fix_reply_is_rejected[interactions-listing-changes] |  |
| 1768 | 干渉を突き合わせた結果が空同然なら exit 1（bypass_tried と同じ空語検査） | test_rejections_review.py::test_fix_reply_is_rejected[interactions-checked-empty-word] |  |
| 1771 | 修正を残したまま破りに行った形跡が無い返答は exit 1 | test_rejections_review.py::test_fix_reply_is_rejected[bypass-not-tried] |  |
| 1773 | 壊しうる面を確かめた結果が空同然なら exit 1 | test_rejections_review.py::test_fix_reply_is_rejected[breaks-result-empty-word] |  |
| 1775 | 症状を塞ぐ修正に「なぜ今それで止めるか」が無ければ exit 1 | test_rejections_review.py::test_fix_reply_is_rejected[symptom-without-why-now] |  |
| 1784 | 判定者が class_query を持つ単位は coverage を省いても coverage では拒まない（赤の理由は… | test_rejections_review.py::test_fix_reply_is_rejected[coverage-omitted-under-judge-query] |  |
| 1789 | coverage に remaining だけを書いた返答も coverage では拒まない（赤の理由は wrote_r… | test_rejections_review.py::test_fix_reply_is_rejected[coverage-remaining-only] |  |
| 1794 | 母数 2 のうち閉鎖を実証した site が 1 件で残りが在るのに remaining が無ければ exit 1（母数… | test_rejections_review.py::test_fix_reply_is_rejected[partial-closure-without-remaining] |  |
| 1796 | 1 行のコマンドの how は型で拒む（欄で書く。 | test_rejections_review.py::test_fix_reply_is_rejected[how-as-one-command] |  |
| 1798 | 走らせられない how は拒む（当たらないパス。 | test_rejections_review.py::test_fix_reply_is_rejected[how-unrunnable] |  |
| 1803 | 覆い: 判定者の母数より狭い how は理由なしで拒む（ | test_rejections_review.py::test_fix_reply_is_rejected[how-narrower-than-judge] |  |
| 1805 | 覆い: 空語（『なし』）の remaining は理由に数えない（ | test_rejections_review.py::test_fix_reply_is_rejected[remaining-empty-word] |  |
| 1808 | 先行例: 修正の先行例に出典が無ければ exit 1（ | test_rejections_review.py::test_fix_reply_is_rejected[fix-precedent-without-source] |  |
| 1813 | 先行例: 判定者の行が在る単位は from_judge_row で採れる（赤の理由は wrote_refs だけ。 | test_rejections_review.py::test_fix_reply_is_rejected[fix-precedent-from-judge-row] |  |
| 1817 | closure.sites が母数を超える返答は exit 1（問いが対象を取りこぼしている） | test_rejections_review.py::test_fix_reply_is_rejected[closure-sites-over-population] |  |
| 1828 | リンク: 申告が空でも、差分が足したリンクの指し先と見出しを引いて拒む（コードスパンの中は拾わない。 | test_rejections_review.py::test_fix_reply_is_rejected[markdown-links-added-by-the-diff] |  |
| 1835 | 残した理由を書けば部分的な覆いは通る（赤の理由は wrote_refs だけ。 | test_rejections_review.py::test_fix_reply_is_rejected[partial-coverage-with-remaining] |  |
| 1839 | 指し先に無い字列は exit 1（どこかに在るかでなく、指し先に在るかを見る。rc= | test_rejections_review.py::test_fix_reply_is_rejected[cite-not-in-target] |  |
| 1844 | 指し先のファイルが無ければ exit 1（『中に無い』とは別の拒否文。 | test_rejections_review.py::test_fix_reply_is_rejected[cite-target-missing] |  |
| 1848 | wrote_refs を落とした返答は型で拒まれる（必須の欄） | test_rejections_review.py::test_fix_reply_is_rejected[wrote-refs-dropped] |  |
| 1853 | 別のファイルに同じ字列が在っても、target に無ければ exit 1（rc= | test_rejections_review.py::test_fix_reply_is_rejected[same-text-in-another-file] |  |
| 1856 | 改行を含む cite は exit 1（修正側には 1 行 1 件の規律だけを言い、指摘側の git grep の理由を… | test_rejections_review.py::test_fix_reply_is_rejected[cite-with-newline] |  |
| 1874 | 修正前の母数 1・修正後に engine が数えた 0 が記録に残る（拒否には使わない。rc= | test_rejections_review.py::test_coverage_before_and_after_are_recorded |  |
| 1877 | 赤を見た修正と見ていない修正（文書）が混じる周の clean は通る——周の全体で見る。返答は out_path から読… | test_rejections_review.py::test_mixed_closure_passes_and_reads_the_out_path |  |

#### simulate.test_rejections

| 行 | 元の check（説明の頭） | 移した先 | 通しに残す |
|---|---|---|---|
| 489 | research を --document 無しで init すると入口で落ち、要る節と穴を名指しする（rc= | test_rejections_research.py::test_init_without_document_names_the_node_and_hole | 子プロセスとして起こした loop.py init の argv と、入口の拒否が 0 以外の終了コードになること（__main__ の写像） |
| 491 | 実在しない --document も入口で落ちる | test_rejections_research.py::test_init_with_missing_document_fails_at_the_entrance | 子プロセスとして起こした loop.py init の argv と終了コード |
| 494 | 最初の節は p0.question（回す側） | test_rejections_research.py::test_first_node_is_the_runner_question |  |
| 496 | 型に合わない返答は exit 1 | test_rejections_research.py::test_reply_outside_the_schema_is_rejected |  |
| 498 | 回す側の降格は exit 1 | test_rejections_research.py::test_runner_cannot_lower_the_thickness |  |
| 500 | 正しい返答は通る | test_rejections_research.py::test_correct_reply_is_accepted |  |
| 502 | 同じ節に 2 回 done は exit 1（回し直しの禁止） | test_rejections_research.py::test_second_done_on_the_same_node_is_rejected |  |
| 504 | optional でない節は省けない | test_rejections_research.py::test_non_optional_node_cannot_be_skipped |  |
| 507 | 2 波目に P0 の残りと先行起動が並ぶ:  | test_rejections_research.py::test_second_wave_has_the_rest_of_p0_and_early_starts |  |
| 508 | 調べ役の agent_type は convergence-loops: 接頭 | test_rejections_research.py::test_investigator_agent_type_has_the_plugin_prefix |  |
| 512 | investigator の前後で作業ツリーが変わると exit 1 | test_rejections_research.py::test_worktree_change_around_the_investigator_is_rejected |  |
| 514 | 理由付きなら通る（痕跡が残る） | test_rejections_research.py::test_accept_tree_change_with_a_reason_passes |  |
| 517 | git_mismatches に理由が残る | test_rejections_research.py::test_accepted_reason_is_kept_in_git_mismatches |  |
| 524 | 回す側の節には文書のパスが渡り、本文は貼られない | test_rejections_research.py::test_runner_node_gets_the_document_path_not_its_body |  |
| 526 | 同じ波の 2 節目（p0.terms）も本文を貼らない | test_rejections_research.py::test_second_runner_node_of_the_wave_does_not_paste_the_body |  |
| 527 | 前の節の出力の穴が埋まっている（空でなく値か『無い』の語） | test_rejections_research.py::test_holes_from_earlier_outputs_are_filled |  |
| 540 | クラスタに入れ漏れた主張があると exit 1 | test_rejections_research.py::test_claim_left_out_of_every_cluster_is_rejected |  |
| 543 | claims_submitted は機械が数える | test_rejections_research.py::test_claims_submitted_is_counted_by_the_engine |  |
| 546 | checker はクラスタごとに並ぶ | test_rejections_research.py::test_checkers_fan_out_per_cluster |  |
| 553 | 材料の正本（items/ のファイル）に材料の欄が在る（欄:  | test_rejections_research.py::test_item_file_keeps_the_material |  |
| 555 | c1 の材料は字数では上限内・バイトでは超過（ | test_rejections_research.py::test_fat_material_is_under_the_limit_in_chars_and_over_in_bytes |  |
| 557 | 太い材料の長い欄は instance から落ち、短い欄（key）は残る（残った:  | test_rejections_research.py::test_long_field_of_a_fat_item_is_dropped_from_the_instance |  |
| 559 | 短い材料は落ちず、落ちた欄が無いことも欄で言う（空でも書く:  | test_rejections_research.py::test_short_item_keeps_everything_and_says_so |  |
| 567 | 上限を超える長さの key でも slim_item は key を落とさない（落とした:  | test_rejections_research.py::test_slim_item_never_drops_the_key |  |
| 570 | 欄ごとに上限未満でも合計が超えれば大きい順に逃がす（残った:  | test_rejections_research.py::test_slim_item_bounds_the_total |  |
| 589 | 柵は 6 綴りとも拾う（拾えた:  | test_rejections_research.py::test_fence_catches_all_six_spellings |  |
| 598 | 射程の外（空白入り・変数の鍵・属性・定数の鍵）は拾わない——拾い始めたら名乗りを広げろ:  | test_rejections_research.py::test_fence_does_not_catch_outside_its_reach |  |
| 599 | 書き手と load_item の中は許す（許しが効いている） | test_rejections_research.py::test_fence_allows_the_writer_and_load_item |  |
| 603 | engine と rules が instance の item を直読みしていない（6 綴りとも。load_item … | test_rejections_research.py::test_engine_and_rules_do_not_read_the_instance_item_directly |  |
| 606 | 大きい欄 1 つを落とせば収まる材料は、その 1 つだけが落ちる（落とした:  | test_rejections_research.py::test_slim_item_drops_the_biggest_field_first |  |
| 609 | checker には他の束の主張も判定も見立ても貼られない | test_rejections_research.py::test_checker_prompt_has_no_other_cluster_or_verdicts |  |
| 617 | 役には束の全員（ | test_rejections_research.py::test_checker_prompt_carries_every_claim_of_the_cluster_to_the_end |  |
| 622 | 役へ渡す schema の断りに、引用符をエスケープしろの 1 行が付く | test_rejections_research.py::test_schema_note_tells_the_role_to_escape_quotes |  |
| 624 | 扇の被覆: 渡した項目に無い id を返すと exit 1（cover の腕） | test_rejections_research.py::test_checker_returning_an_id_it_was_not_given_is_rejected |  |
| 626 | 語彙に無い判定語は節の schema（検証器の語彙の写し——graphcheck が包含を見る）で exit 1 | test_rejections_research.py::test_verdict_outside_the_vocabulary_is_rejected |  |
| 628 | 判定が欠けた主張は欠けた分だけ出し直す | test_rejections_research.py::test_missing_verdicts_are_reissued |  |
| 630 | 済んだ instance にはもう done できない | test_rejections_research.py::test_done_instance_cannot_be_done_again |  |
| 633 | 欠けた分の checker と、返った分の refuter が同じ波に出る（pipeline）:  | test_rejections_research.py::test_reissued_checker_and_refuter_share_a_wave |  |
| 635 | refuter の upheld と verdict の食い違いは exit 1 | test_rejections_research.py::test_refuter_upheld_and_verdict_must_agree |  |
| 637 | 相違に correction が無いと exit 1（検証器の規則を先取り） | test_rejections_research.py::test_discrepancy_without_correction_is_rejected |  |
| 639 | 欄が揃えば通る | test_rejections_research.py::test_complete_discrepancy_is_accepted |  |
| 643 | patch は痕跡付き | test_rejections_research.py::test_patch_leaves_a_trace |  |
| 655 | check_record は語彙に無い verdict を拒む（ | test_rejections_research.py::test_check_record_rejects_a_verdict_written_by_patch |  |
