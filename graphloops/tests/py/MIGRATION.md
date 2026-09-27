# bash の台本から pytest への移し替えの対応表

graphloops/tests/simulate.py・simulate_review.py（bash の tests/run.sh が束ねる台本）の検査を、このディレクトリの pytest へ段ごとに移した記録。段の名前（S2b ほか）はリポジトリの外の計画 testplan/PLAN.md の段。移すときの決まりは [README の「pytest の置き場」](../../README.md#pytest-の置き場graphloopstestspy)。

- 台本の check 1 件をテスト 1 件（parametrize の 1 行か 1 関数）に写す。件数の柵（conftest.py の EXPECTED_ITEMS）が check の粒度で数え続け、落ちた検査が 1 件ずつ並ぶ
- 盤面を端から端まで回す筋書きは、本文を台本の check のまま移し、土台の gl_script で台本のモジュールを借りる。件数は EXPECTED_SIM_CHECKS が数える
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
