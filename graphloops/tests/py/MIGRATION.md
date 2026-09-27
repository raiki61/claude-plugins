# bash の台本から pytest への移し替えの対応表

graphloops/tests/simulate.py・simulate_review.py（bash の tests/run.sh が束ねる台本）の検査を、このディレクトリの pytest へ段ごとに移した記録。段の名前（S2b ほか）はリポジトリの外の計画 testplan/PLAN.md の段。移すときの決まりは [README の「pytest の置き場」](../../README.md#pytest-の置き場graphloopstestspy)。

- 台本の check 1 件をテスト 1 件（parametrize の 1 行か 1 関数）に写す。件数の柵（conftest.py の EXPECTED_ITEMS）が check の粒度で数え続け、落ちた検査が 1 件ずつ並ぶ
- 盤面を端から端まで回す筋書きは、本文を台本の check のまま移し、土台の gl_script で台本のモジュールを借りる。件数は EXPECTED_SIM_CHECKS が数える
- 途中の盤面に 1 手を当てて確かめる検査（否定検査など）は、控えた波・1 手・手で書いた期待（assert）の形に移す（T1）。波は waves.py が台本の前半を同じプロセスで 1 度だけ回して控え、検査ごとに控えから始める。台本の check は数えない（EXPECTED_SIM_CHECKS は動かない）。行き先は各テストの印 `moved_from` が名乗り、台帳（ledger.py）が台本の check ごとに機械で組む——空欄と、名乗りが check にちょうど 1 件で当たらない物と、末尾の「check ごとの対応（台帳が刷る）」の塊の古びは test_ledger.py が赤にする
- 上限で止まる・止める・人待ちのように盤面を何周も回して狙いの点を見る筋書きは、出来事の列のデータ（scenes.py の history。台本の関数の中の Run 1 つが打った出来事を元の順に並べる）に書き、行はその列の印を指す（T2・層 2）。行の前置きは印の手前の出来事の全部、when は印の出来事、期待は手で書く述語。1 行が台本の check 1 件で、行の印が名乗る。形の規範は [ADR 0067](../../../docs/adr/0067-test-migration-layer2-and-removal-conditions.md)
- 台本→移し先の対応の正本は印 `moved_from` 1 つ。台帳が見張る台本は、印が名乗る台本と、基の git の版の塊に載っていた台本の和で、見張りから外すのは末尾の「外した台本」の一覧への 1 行だけ
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

否定検査 2 本（simulate_review.py と simulate.py の test_rejections）の check を、控えた波・1 手・手で書いた期待の pytest に移した。**台本はまだ消していない**——台本を消すのは、下の変異の腕の証明が CI で済んだ後の run（[ADR 0067 の台本を消す 4 条件](../../../docs/adr/0067-test-migration-layer2-and-removal-conditions.md#台本を消す-4-条件)）。それまでは同じ検査が両方に在り、片方を直したらもう片方も直す。台帳（下の test_ledger.py）は、台本の check が増える・減る・説明の頭が変わるずれを赤にするが、説明はそのままで条件だけが変わったずれは捕まえない（waves.py の前半の手順の写しも見張りは無い）。

| 元の台本の関数 | 移した先 |
|---|---|
| simulate_review.py の test_rejections | test_rejections_review.py（すべて medium） |
| simulate.py の test_rejections | test_rejections_research.py（盤面を使う物は medium、engine の部品とソースを直に見る物は small） |

check の数は、末尾の「check ごとの対応（台帳が刷る）」の塊の、この 2 関数の表の行の数（ledger.py が今の台本から刷る）。

- **途中の盤面を作る口**（waves.py）: 台本の Run・answers・base_answers・settle を import して借り、glharness.driven(台本, "inproc") の下で前半を同じプロセスで回す（git は本物）。波ごとに Run の作業場（型のリポジトリ・盤面・設定）をまるごと控え、検査は同じ置き場へ控えを写し戻して始める（盤面の中の絶対パスを書き換えない）。控えは worker ごとの session の fixture で 1 度だけ作る。台本の test_rejections だけに在る前半の手順（主張 A を太らせる・stray.txt と --accept-tree-change・拒ませてから通す done）は waves.py に写してある
- **台帳**（ledger.py・test_ledger.py）: 台本の関数の中の check を ast で並べ、各テストの印 `moved_from(台本, 説明の頭, kept=通しに残す理由)` と突き合わせる。表は `python3 graphloops/tests/py/ledger.py` が刷った物（T2 から末尾の塊に移した）
- **件数の定数**: conftest.py の EXPECTED_ITEMS に、移した先の 2 ファイル（この 2 関数の表の行の数と同じ）・台帳の柵（test_ledger.py の 5）・波の写し戻しの消す口の守り（test_harness.py の 3）を足した（値の正本は conftest.py。pytest --collect-only の実測に合わせる）。graphloops/tests/run.sh の EXPECTED_CHECKS・EXPECTED_TESTS は台本を消していないので変えない。EXPECTED_SIM_CHECKS も変えない（新しい検査は台本の check を呼ばない）

### 通しに残す物

同じプロセスの検査では見えない物は、移した先のテストで中身を見た上で、台本（子プロセスで loop.py を起こす通し）にも残す。表の「通しに残す」の列が理由:

- loop.py record の子プロセスの標準出力と終了コード（台本が CLI の煙を置く唯一の所）
- PYTHONIOENCODING=cp1252 の下での標準入力の読み（起動時にだけ効く設定。3 OS の通しで windows-latest だけ赤だった腕）
- loop.py init の argv と、入口の拒否が 0 以外の終了コードになること（2 件）

### 被覆の包含（台本を消す条件の 4）

道具は cover_moved.py（撃つのは CI の手で起こす job .github/workflows/cover-moved.yml。pytest の一式には入れない。打ち方と今の測り方は docstring）。T1 の撃ちの時点では、旧い側は台本 2 関数を glharness の inproc の口で 1 回ずつ回して測り（loop.py が同じプロセスに回るので engine の行が測れる。cli の口のまま測ると旧い側が部品の行だけになり、包含が恒真になる）、新しい側は移した先の 2 ファイルを pytest-cov の --cov-context=test で測る（前の回の測りは使い回さない）。波は --gl-prebuild-waves で最初のテストの準備（setup）に全部作らせ、検査の本体（run）と分けて数える。計測器は ctrace（Python 3.14 の既定の sysmon は動的な文脈を持たない）。測る行は graphloops/engine・rules・scripts。

2026-09-27 の測り（**土台 aa4cdf6 の版の上の値**。0.21.5 の上ではまだ測り直していない——台本も engine も行が動いたので、下の数字を今の版の包含の証明として読まない。測り直しは上の道具を今の版で 1 回撃つ。Python 3.14・coverage 7.16.1・pytest-cov 7.1.0・testslot の枠の中）:

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

所要（同じ回。aa4cdf6 の版）: 旧い側は inproc と ctrace の下で review 5.9 秒（74 件）・research 0.9 秒（43 件）。新しい側は 117 件を 1 プロセスで 18 秒前後（被覆つき）。被覆なしの 1 プロセスでは review 11.1 秒・research 4.0 秒——同じプロセスで回した台本より速くはない（1 件ごとに控えを写し戻し、1 手を打つため）。cli の口の台本の所要はこの run では測っていない（台本を回したのは被覆の 1 回だけ）。この段が変えたのは速さでなく、1 件ずつ独立に落ち、pytest-xdist で割れ、子の Python を起こさない形である。

### 変異の腕

tests/mutations.json で test_rejections を当てにする腕は下の表のとおり。この run では腕を動かしていない（台本は残り、腕は今も台本で撃てる）。**撃つのは CI だけ**（人の方針）。腕の実行器 tests/mutate.py は、差分から機械で作る腕（--auto）では pytest の段を持つが、手書きの腕（tests/mutations.json の一覧）は台本だけを撃ち、pytest の node id を撃つ口を持たない。下の手順は、手書きの腕が pytest を撃つ口が入ってから CI で撃つ:

1. 口が入った版で、下の腕を 1 本ずつ、tests に「移した先」の node id だけを書いて撃つ（台本は tests から外す）
2. Killed で、落ちたテストが「移した先」の node id なら、その腕の tests を node id に付け替えてよい。expect は腕の中身の文言のままで、新しいテストの失敗の文面に当たるかを見る（当たらなければ expect を新しいテストの assert の文面に替える）
3. Survived なら付け替えない。台帳の行に理由を書き、台本を消す run の前に新しいテストを足す
4. 表の腕が全部付け替わり、前の変異の結果で台本 2 本が殺した自動の腕（台本を消す条件の 3）も新しいテストで殺せたら、台本 2 本を消す run の条件がそろう

| 腕 | 撃つファイル | expect（頭） | 殺すはずのテスト（移した先） |
|---|---|---|---|
| e08 | review-loop.py | 改行を含む cite は exit 1 | test_rejections_review.py::test_fix_reply_is_rejected[cite-with-newline] |
| e20 | review-loop.json | wrote_refs を落とした返答は型で拒まれる | test_rejections_review.py::test_fix_reply_is_rejected[wrote-refs-dropped] |
| f06 | review-loop.py | 改行を含む cite は exit 1 | test_rejections_review.py::test_fix_reply_is_rejected[cite-with-newline] |
| m11 | review-loop.py | 残した理由を書けば部分的な覆いは通る | test_rejections_review.py::test_fix_reply_is_rejected[partial-coverage-with-remaining] |
| K5a | review-loop.py | 修正前の母数 1・修正後に engine が数えた 0 が記録に残る | test_rejections_review.py::test_coverage_before_and_after_are_recorded |
| K5b | review-loop.py | 修正前の母数 1・修正後に engine が数えた 0 が記録に残る | test_rejections_review.py::test_coverage_before_and_after_are_recorded |
| K9 | review-loop.py | 判定者の書いた件数は engine が数えた件数に置き換わり、置き換えたことが | test_rejections_review.py::test_judge_count_is_replaced_by_the_engine_count |
| P01 | validator.py | inspector は Read を持っても本文を貼る | test_rejections_review.py::test_inspector_gets_pasted_body_and_investigator_gets_a_path |
| R06 | review-loop.py | 先行例: 直す単位の行が欠けた judge の返答は exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[precedent-row-missing] |
| R07 | review-loop.py | 先行例: 人へ回す問いに決まらない理由が無ければ exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[human-question-needs-undecided-because] |
| R08 | review-loop.py | 先行例: 修正の先行例に出典が無ければ exit 1 | test_rejections_review.py::test_fix_reply_is_rejected[fix-precedent-without-source] |
| R13 | review-loop.py | リンク: 申告が空でも | test_rejections_review.py::test_fix_reply_is_rejected[markdown-links-added-by-the-diff] |
| O01 | advance.py | 返答の置き場のディレクトリは engine が作る | test_rejections_review.py::test_out_path_directories_are_made_by_the_engine |
| NF1 | review-loop.py | 先行例: 見つからないなら何を探したかが要る | test_rejections_review.py::test_judge_reply_is_rejected[not-found-without-searched] |
| RN2 | review-loop.json | 順位（主経路）: 外部標準照合の done は | test_rejections_review.py::test_external_standards_without_rankings_none_is_rejected |
| PD1 | review-loop.py | 先行例: 同じ key の行が 2 つある judge の返答は exit 1 | test_rejections_review.py::test_judge_reply_is_rejected[precedent-key-duplicated] |
| PE1 | review-loop.py | 先行例: 人へ回す問い（escalate）にも先行例の行が要る | test_rejections_review.py::test_judge_reply_is_rejected[escalate-needs-precedent] |
| NR1 | review-loop.py | 覆い: 判定者の母数より狭い how は理由なしで拒む | test_rejections_review.py::test_fix_reply_is_rejected[how-narrower-than-judge] |
| BR1 | review-loop.py | 覆い: 空語（『なし』）の remaining は理由に数えない | test_rejections_review.py::test_fix_reply_is_rejected[remaining-empty-word] |
| DG1 | advance.py | 任せ先: graph が delegate を宣言した回す側の節は | test_rejections_review.py::test_undeclared_repo_falls_back_to_a_delegate |

### check ごとの対応

T2 から、台本ごとの表は末尾の「check ごとの対応（台帳が刷る）」の塊 1 つに刷る（simulate_review.test_rejections・simulate.test_rejections の表もそこに在る）。

## T2（2026-09-27）

上限で止まる類と、止める・人待ちの筋書き（移す順の (1)(2)。[ADR 0067 の移す順](../../../docs/adr/0067-test-migration-layer2-and-removal-conditions.md#移す順)）の台本 14 関数の check を、層 2 の筋書き——出来事の列のデータと、その列の印を指す行——に移した。**台本はまだ消していない**（消す条件は T1 と同じ 4 つ。下の変異の腕と被覆の手順を CI で撃った後の run）。それまでは同じ検査が両方に在り、片方を直したらもう片方も直す。

| 元の台本の関数 | 移した先 |
|---|---|
| simulate_review.py の test_runaway・test_ci_red_runaway・test_no_new_awaiting_after_judge・test_awaiting・test_awaiting_origin_guards・test_final_gate_empty_asks_human・test_stop_midround・test_stop_after_round・test_human_gate | test_scenarios_review.py（同じ名前の関数。すべて medium・layer2） |
| simulate.py の test_unattended_stuck・test_attended_stuck_answer・test_gate_arms・test_stopped_before_gates_reports・test_stop_midway | test_scenarios_research.py（同じ名前の関数。すべて medium・layer2） |

check の数は、末尾の塊のこの 14 関数の表の行の数。範囲は判定の推し: test_spec_stop_and_changes（仕様の道。移す順の (4)）は次の run、test_count_budget・test_stopped_gates_all_thicknesses・test_stop_branch・test_escalate_ratchet・test_stuck_routed_at_judge は Run を作らない規則の検査なので層 1 の仕事で、この段では移していない。

- **形・回し手・役の表・控え・台本の check を撃たない決まり**: 正本は scenes.py の docstring（規範は [ADR 0067](../../../docs/adr/0067-test-migration-layer2-and-removal-conditions.md)）。ここに残す記録は 1 つ——1 周目の形では行が手前の出来事を選んで落とせ、test_stop_after_round の status・finalize・trace の 3 行が、元の関数が先に打った next・status・finalize を落としていた（2 周目で「前置きは印の手前の出来事の全部」の形に直した）
- **元の関数との突き合わせ**: 正本は cover_moved.py の docstring（--no-cov の回が、loop.py の呼び出しの列と最後の盤面の両方を比べる）。撃った結果は下の「所要と子の数」
- **関数の外の check**: test_attended_stuck_answer が呼ぶ loop_shape_held の check は台本の関数の本文に無く台帳に載らない。同じ期待を印の無いテスト test_attended_stuck_answer_keeps_the_loop_shape に写した
- **大きさと印**: 盤面を回すので全部 medium（理由は glharness.py の docstring）。印 layer2 も付けた（手元の反復は `-m "not layer2"` で外せる）
- **通しに残す物**: test_stop_midround と test_human_gate の主経路（Run("gate")）は通しに残す 10 本（[ADR 0067 の通しに残す 10 本](../../../docs/adr/0067-test-migration-layer2-and-removal-conditions.md#通しに残す-10-本)）。印の kept に理由を書いた（cli の口の台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手）

### 台帳の変わり目

- 見張る台本と移し先のファイルを手で書いた一覧（ledger.py の SCRIPTS・MOVED_FILES）と、被覆の道具の台本→移し先の字の頭の決め打ちを消し、印 `moved_from` 1 つから引く。見張る台本は「印が名乗る台本」と「**基の git の版**の塊に載っていた台本」の和から「外した台本」の一覧の台本を引いた集合——印を全部消しても、塊の節を消しても、刷り直して貼っても、基の版の塊に載った台本は「名乗るテストが無い」で赤になる。赤を解くのは下の「外した台本」への 1 行（台本と理由）だけ。基は CI では PR の基か push の直前の版（test.yml の pytest の段の GL_LEDGER_BASE。checkout は全履歴）、手元では HEAD と main との merge-base。基を引けない checkout と変異の実行器の写しの中では突合を見送り、見送りの行（`# SKIP ledger-base:`）を pytest の警告に出す（人の関所 2026-09-27 の 2 回目の条件 1・2）
- ループの中の check と、説明の頭の型紙の規則は ledger.py の docstring（名前に束ねたループは、字面の tuple にちょうど 1 度だけ束ねた物だけを読む）

### 件数の定数

conftest.py の EXPECTED_ITEMS 1349 → 1532。内訳は、層 2 の 2 ファイル 110 件（review 72・research 38。印の無い 1 件は関数の外の check の写し）、回し手の部品 test_scenes.py 15、台帳の柵 5 → 46、被覆の道具 4 → 13、fence の集めるだけの回の柵 3、変異の写しの印 1。値の正本は conftest.py（pytest --collect-only の実測）。**並行の束 A（wip/bunda）も同じ行を書き換える**——合流した版で --collect-only を数え直して書く。graphloops/tests/run.sh の EXPECTED_CHECKS・EXPECTED_TESTS と EXPECTED_SIM_CHECKS・VOCAB_REACHED は、台本を消していないので変えない。

### 所要と子の数（見積もりの置き換え先）

2026-09-27 に、この木（0.21.5 の上）で測った。testslot の枠の中で、手元で名指したのは代表の 3 関数だけ（人の方針）。全部の関数の比べは CI の cover-moved の job で撃つ。

旧い側（元の関数を名指しで回す）と層 2 の側（その関数の行が使う列を控えの置き場で端まで 1 度ずつ作る）の比べ（cover_moved.py --no-cov）。子の数は監査イベント subprocess.Popen で数えた（cli の口は子の中の子が見えないので所要だけ）:

| 台本の関数 | 旧い側 cli（秒） | 旧い側 inproc（秒・git／python／他） | 層 2 の列（秒・git／python／他） | 元の関数の Run との突き合わせ |
|---|---|---|---|---|
| simulate_review.test_runaway | 29.5 | 16.7・550／12／11 | 16.7・550／12／11 | 1 列とも一致 |
| simulate_review.test_stop_after_round | 測っていない | 15.9・551／13／11 | 16.4・551／13／11 | 4 列とも一致 |
| simulate.test_stop_midway | 測っていない | 1.7・38／5／0 | 1.9・38／5／0 | 3 列とも一致 |

- 層 2 の列を作る費用は、inproc の口の旧い側とほぼ同じ（同じ drive を回し、engine の子——git・検証器・走らせる語——も同じ数だけ起きる）。この段の効き目は速さでなく、行が 1 件ずつ独立に落ち、控えを共にし、元の関数の出来事を落とせない形である。子が減るのは世界の口と偽の git（T3）の後
- 見積もりの「1 手を同じプロセスで 10〜30 ミリ秒」は、この段の層 2 では成り立たない
- 層 2 の 2 ファイルを 1 プロセス（-n 無し・被覆なし）で 1 回ずつ回した所要: review（72 件）118.7 秒、research（38 件——上の件数の定数の内訳と同じ）8.7 秒
- 一式の所要はこの段で延びる（台本 14 関数も残り、同じ振る舞いを 2 度確かめる）。pytest-xdist の worker は控えを別々に作るので、同じ列を worker の数まで作り直しうる。延びるのは台本を消す run までの一時の措置（人の関所 2026-09-27 の条件 3）

### 変異の腕

tests/mutations.json で T2 の台本を当てにする手書きの腕は 12 本。(1) 上限で止まる類の 4 関数（test_runaway・test_ci_red_runaway・test_gate_arms・test_stopped_before_gates_reports）を指す手書きの腕は 0 本で、移した期待の強さの証明は台本を消す条件の 3（自動の腕）だけが担う——条件 4（被覆）は行を通したことしか示さない。手順は T1 の変異の腕の節と同じ（手書きの腕が pytest の node id を撃つ口が入った版で、CI で撃つ）。

| 腕 | 撃つファイル | expect（頭） | 殺すはずのテスト（移した先） |
|---|---|---|---|
| R05 | review-loop.py | 書いた時点: 人に諮っている欄を後の工程が clean で上書きすると拒む | test_scenarios_review.py::test_awaiting_origin_guards[ci-overwrite] |
| J01 | review-loop.json | CI を再実行する節のプロンプトに、この周の問いの台帳が渡る | test_scenarios_review.py::test_awaiting_origin_guards[ci-prompt-has-ledger] |
| MP1 | review-loop.py | 主経路の観測: 見たと言う状態なのに観測した値が無ければ exit 1 | test_scenarios_review.py::test_awaiting[observed-empty] |
| OA1 | review-record.py | 書いた時点: 人に諮っている欄を後の工程が | test_scenarios_review.py::test_awaiting_origin_guards[ci-overwrite] |
| RV2 | review-loop.py | 判定の後の人待ち: 問いの無い awaiting_human を書いた p4.ci は拒む | test_scenarios_review.py::test_no_new_awaiting_after_judge[p4-ci-awaiting-without-question] |
| NA1 | review-loop.py | 判定の後の人待ち: 問いの無い awaiting_human を書いた p4.ci は拒む | test_scenarios_review.py::test_no_new_awaiting_after_judge[p4-ci-awaiting-without-question] |
| RC1 | advance.py | 1 周目の締めの後の next が stopped と halted | test_scenarios_review.py::test_stop_after_round[stops-after-round-1] |
| FG1 | review-loop.py | 撃てた腕が 0 本の関門で収束を言わず人に諮る | test_scenarios_review.py::test_final_gate_empty_asks_human[asks-on-empty-gate] |
| FG2 | review-loop.py | 人が認めた木なら | test_scenarios_review.py::test_final_gate_empty_asks_human[converges-next-round] |
| FG3 | review-loop.py | 諮る前に止めた理由（stop_reason）を立てる | test_scenarios_review.py::test_final_gate_empty_asks_human[stop-reason-before-asking] |
| FG4 | review-loop.py | 上限の周の continue は上限を 1 周だけ延ばし | test_scenarios_review.py::test_final_gate_empty_asks_human[continue-extends-by-one] |
| CK3 | review-loop.py | 判定の時点: 人待ちの素材を出どころにする問いを台帳に載せない判定は拒む | test_scenarios_review.py::test_awaiting_origin_guards[judge-unlisted] |

### 被覆の包含

cover_moved.py が名乗るのは実行の包含（台本の関数が通した行を、移した先のテストの和も通したか）だけで、期待の強さは名乗らない。台本ごとの比べ（per_script）は、台本を名乗る node id の本体（run）と、そのテストが使った前置きの作り（T1 の波とその祖先・層 2 の列の接頭辞。fixture が user_properties に積み、--junitxml で読む）だけを数える。被覆の回（--gl-prebuild-waves）は前置きだけを準備の段で作り、各行の when を本体で打つので、どの行も run の文脈を持つ——「名乗る node id が run の文脈に 1 つも無い台本は赤」の規則はそのまま当てる。

**被覆の回は、この run では撃っていない**（手元に coverage と pytest-cov が無く、人の方針で手元では関数を名指しした数件だけを回す）。撃つのは CI の cover-moved の job（.github/workflows/cover-moved.yml。手で起こす）で、台本を消す run の前に撃つ。縛ったのは選ぶ段の純粋な関数（select_new・used_contexts・lineage）と子の数え方で、test_cover_moved.py と test_scenes.py が見る。--no-cov の回（所要・子の数・元の関数の Run との突き合わせ）は上の 3 関数で撃った。T1 の上の測りも土台 aa4cdf6 の版の値のままで、今の版の包含の証明としては読めない。

## 外した台本

台帳の見張りから外した台本（``- `<台本>`: <理由>`` の 1 行ずつ。追記だけ。基の git の版の塊に載っていた台本を見張りから外す口はここだけ）。

（まだ無い）

## check ごとの対応（台帳が刷る）

`python3 graphloops/tests/py/ledger.py` が刷った塊。手で直さない（test_ledger.py が完全な一致を見る）。表の「元の check」は台本の check の説明の頭（f 字列の穴は `{式}` の型紙）、「ループ」はループの中の check の回数（型紙 ×N は行き先を N 本に縛る）。


<!-- ledger:begin -->
#### simulate.test_attended_stuck_answer

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 457 | 人に聞く番になる |  | test_scenarios_research.py::test_attended_stuck_answer[asks-human] |  |
| 459 | answer escalate が通る |  | test_scenarios_research.py::test_attended_stuck_answer[escalate-accepted] |  |
| 461 | 重厚で 3 周目に入る: {st['thickness']} r{st['round']} |  | test_scenarios_research.py::test_attended_stuck_answer[heavy-round-3] |  |
| 463 | stuck 後の重厚では断面の生成が開く |  | test_scenarios_research.py::test_attended_stuck_answer[generation-opens] |  |
| 464 | 重厚に上がると cartographer が序盤に出る |  | test_scenarios_research.py::test_attended_stuck_answer[cartographer-early] |  |

#### simulate.test_gate_arms

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 1313 | cold_reader が pass しないまま上限で stopped（{sr[:40]}） |  | test_scenarios_research.py::test_gate_arms[coldfail-stops-at-max] |  |
| 1315 | 何を聞かれて止まったかが記録に残る（{hi[-1].get('kinds') if hi else None}） |  | test_scenarios_research.py::test_gate_arms[asked-kinds-kept] |  |
| 1316 | 収束を名乗らず、ゲートの周ごとの verdict が残る |  | test_scenarios_research.py::test_gate_arms[gate-verdicts-kept] |  |
| 1317 | 止まった周は max_rounds（{run.state()['round']}） |  | test_scenarios_research.py::test_gate_arms[stopped-at-max-rounds] |  |
| 1321 | rederiver の redesign-needed が 2 周解消しないと人に聞く（{last.get('ask',… |  | test_scenarios_research.py::test_gate_arms[rederiver-asks] |  |

#### simulate.test_rejections

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 493 | research を --document 無しで init すると入口で落ち、要る節と穴を名指しする（rc={r.re… |  | test_rejections_research.py::test_init_without_document_names_the_node_and_hole | 子プロセスとして起こした loop.py init の argv と、入口の拒否が 0 以外の終了コードになること（__main__ の写像） |
| 495 | 実在しない --document も入口で落ちる |  | test_rejections_research.py::test_init_with_missing_document_fails_at_the_entrance | 子プロセスとして起こした loop.py init の argv と終了コード |
| 498 | 最初の節は p0.question（回す側） |  | test_rejections_research.py::test_first_node_is_the_runner_question |  |
| 500 | 型に合わない返答は exit 1 |  | test_rejections_research.py::test_reply_outside_the_schema_is_rejected |  |
| 502 | 回す側の降格は exit 1 |  | test_rejections_research.py::test_runner_cannot_lower_the_thickness |  |
| 504 | 正しい返答は通る |  | test_rejections_research.py::test_correct_reply_is_accepted |  |
| 506 | 同じ節に 2 回 done は exit 1（回し直しの禁止） |  | test_rejections_research.py::test_second_done_on_the_same_node_is_rejected |  |
| 508 | optional でない節は省けない |  | test_rejections_research.py::test_non_optional_node_cannot_be_skipped |  |
| 511 | 2 波目に P0 の残りと先行起動が並ぶ: {sorted(by)} |  | test_rejections_research.py::test_second_wave_has_the_rest_of_p0_and_early_starts |  |
| 512 | 調べ役の agent_type は convergence-loops: 接頭 |  | test_rejections_research.py::test_investigator_agent_type_has_the_plugin_prefix |  |
| 516 | investigator の前後で作業ツリーが変わると exit 1 |  | test_rejections_research.py::test_worktree_change_around_the_investigator_is_rejected |  |
| 518 | 理由付きなら通る（痕跡が残る） |  | test_rejections_research.py::test_accept_tree_change_with_a_reason_passes |  |
| 521 | git_mismatches に理由が残る |  | test_rejections_research.py::test_accepted_reason_is_kept_in_git_mismatches |  |
| 528 | 回す側の節には文書のパスが渡り、本文は貼られない |  | test_rejections_research.py::test_runner_node_gets_the_document_path_not_its_body |  |
| 530 | 同じ波の 2 節目（p0.terms）も本文を貼らない |  | test_rejections_research.py::test_second_runner_node_of_the_wave_does_not_paste_the_body |  |
| 531 | 前の節の出力の穴が埋まっている（空でなく値か『無い』の語） |  | test_rejections_research.py::test_holes_from_earlier_outputs_are_filled |  |
| 544 | クラスタに入れ漏れた主張があると exit 1 |  | test_rejections_research.py::test_claim_left_out_of_every_cluster_is_rejected |  |
| 547 | claims_submitted は機械が数える |  | test_rejections_research.py::test_claims_submitted_is_counted_by_the_engine |  |
| 550 | checker はクラスタごとに並ぶ |  | test_rejections_research.py::test_checkers_fan_out_per_cluster |  |
| 557 | 材料の正本（items/ のファイル）に材料の欄が在る（欄: {sorted(c1full)}） |  | test_rejections_research.py::test_item_file_keeps_the_material |  |
| 559 | c1 の材料は字数では上限内・バイトでは超過（{chars} 字）——落ちること自体がバイトで測っている証拠になる |  | test_rejections_research.py::test_fat_material_is_under_the_limit_in_chars_and_over_in_bytes |  |
| 561 | 太い材料の長い欄は instance から落ち、短い欄（key）は残る（残った: {sorted(ch['c1']['i… |  | test_rejections_research.py::test_long_field_of_a_fat_item_is_dropped_from_the_instance |  |
| 563 | 短い材料は落ちず、落ちた欄が無いことも欄で言う（空でも書く: {ch['c2'].get('item_omitted')… |  | test_rejections_research.py::test_short_item_keeps_everything_and_says_so |  |
| 571 | 上限を超える長さの key でも slim_item は key を落とさない（落とした: {fat_omitted}） |  | test_rejections_research.py::test_slim_item_never_drops_the_key |  |
| 574 | 欄ごとに上限未満でも合計が超えれば大きい順に逃がす（残った: {sorted(many_slim)} / 落とした: {… |  | test_rejections_research.py::test_slim_item_bounds_the_total |  |
| 593 | 柵は 6 綴りとも拾う（拾えた: {len(caught)}/6） |  | test_rejections_research.py::test_fence_catches_all_six_spellings |  |
| 602 | 射程の外（空白入り・変数の鍵・属性・定数の鍵）は拾わない——拾い始めたら名乗りを広げろ: {slipped} |  | test_rejections_research.py::test_fence_does_not_catch_outside_its_reach |  |
| 603 | 書き手と load_item の中は許す（許しが効いている） |  | test_rejections_research.py::test_fence_allows_the_writer_and_load_item |  |
| 607 | engine と rules が instance の item を直読みしていない（6 綴りとも。load_item … |  | test_rejections_research.py::test_engine_and_rules_do_not_read_the_instance_item_directly |  |
| 610 | 大きい欄 1 つを落とせば収まる材料は、その 1 つだけが落ちる（落とした: {order_omitted}） |  | test_rejections_research.py::test_slim_item_drops_the_biggest_field_first |  |
| 613 | checker には他の束の主張も判定も見立ても貼られない |  | test_rejections_research.py::test_checker_prompt_has_no_other_cluster_or_verdicts |  |
| 621 | 役には束の全員（{want_ids}）が、本文の末尾まで渡る（材料: {got_ids} / 欠けた主張: {missi… |  | test_rejections_research.py::test_checker_prompt_carries_every_claim_of_the_cluster_to_the_end |  |
| 626 | 役へ渡す schema の断りに、引用符をエスケープしろの 1 行が付く |  | test_rejections_research.py::test_schema_note_tells_the_role_to_escape_quotes |  |
| 628 | 扇の被覆: 渡した項目に無い id を返すと exit 1（cover の腕） |  | test_rejections_research.py::test_checker_returning_an_id_it_was_not_given_is_rejected |  |
| 630 | 語彙に無い判定語は節の schema（検証器の語彙の写し——graphcheck が包含を見る）で exit 1 |  | test_rejections_research.py::test_verdict_outside_the_vocabulary_is_rejected |  |
| 632 | 判定が欠けた主張は欠けた分だけ出し直す |  | test_rejections_research.py::test_missing_verdicts_are_reissued |  |
| 634 | 済んだ instance にはもう done できない |  | test_rejections_research.py::test_done_instance_cannot_be_done_again |  |
| 637 | 欠けた分の checker と、返った分の refuter が同じ波に出る（pipeline）: {ids} |  | test_rejections_research.py::test_reissued_checker_and_refuter_share_a_wave |  |
| 639 | refuter の upheld と verdict の食い違いは exit 1 |  | test_rejections_research.py::test_refuter_upheld_and_verdict_must_agree |  |
| 641 | 相違に correction が無いと exit 1（検証器の規則を先取り） |  | test_rejections_research.py::test_discrepancy_without_correction_is_rejected |  |
| 643 | 欄が揃えば通る |  | test_rejections_research.py::test_complete_discrepancy_is_accepted |  |
| 647 | patch は痕跡付き |  | test_rejections_research.py::test_patch_leaves_a_trace |  |
| 659 | check_record は語彙に無い verdict を拒む（{errs[:1]}） |  | test_rejections_research.py::test_check_record_rejects_a_verdict_written_by_patch |  |

#### simulate.test_stop_midway

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 2899 | 止める: 止めた時点で convergence に理由が入る（{r.stderr[-160:]}{rec['conver… |  | test_scenarios_research.py::test_stop_midway[reason-in-convergence] |  |
| 2902 | 止める: 次の next は後始末の節だけを出す（{[i['node'] for i in nx['ready']]}） |  | test_scenarios_research.py::test_stop_midway[next-is-adapt-only] |  |
| 2906 | 止める: 報告まで届き、記録は検証器を通る（exit {v.returncode}: {(v.stdout + v.st… |  | test_scenarios_research.py::test_stop_midway[report-and-validator] |  |
| 2909 | 止める: 照合の前に止めたので主張とクラスタは空で、その理由が残る（{sorted(rec['process'].get… |  | test_scenarios_research.py::test_stop_midway[stopped-gaps] |  |
| 2918 | 止める: 最初の節の前に止めても報告まで届き、空の欄に理由が付く（{last.get('status')}・{sorte… |  | test_scenarios_research.py::test_stop_midway[stop-before-first-node] |  |
| 2935 | 途中の finalize: 記録を書き換えず、未決として exit 1（exit {r.returncode}・足された… |  | test_scenarios_research.py::test_stop_midway[early-finalize-undecided] |  |
| 2942 | 途中の finalize の後に止めた run は、止めた事実で畳む（{conv}） |  | test_scenarios_research.py::test_stop_midway[stopped-after-early-finalize] |  |

#### simulate.test_stopped_before_gates_reports

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 2858 | {th}: 上限を 1 周にできる（{r.stderr.strip()[-120:]}） | 型紙 ×2 | test_scenarios_research.py::test_stopped_before_gates_reports[std-max-rounds-1]<br>test_scenarios_research.py::test_stopped_before_gates_reports[heavy-max-rounds-1] |  |
| 2869 | {th}: 上限で人に聞く（{last.get('ask', {}).get('kinds')}） | 型紙・1 本以上（if の下に在る） | test_scenarios_research.py::test_stopped_before_gates_reports[std-asks-at-max] |  |
| 2871 | {th}: stop と答えられる | 型紙・1 本以上（if の下に在る） | test_scenarios_research.py::test_stopped_before_gates_reports[std-answer-stop] |  |
| 2874 | {th}: 止まった run として終わる（{last['status']}） | 型紙 ×2 | test_scenarios_research.py::test_stopped_before_gates_reports[std-ends-stopped]<br>test_scenarios_research.py::test_stopped_before_gates_reports[heavy-ends-stopped] |  |
| 2875 | {th}: ゲートが走る前に止まっても report.md が出る | 型紙 ×2 | test_scenarios_research.py::test_stopped_before_gates_reports[std-report]<br>test_scenarios_research.py::test_stopped_before_gates_reports[heavy-report] |  |
| 2877 | {th}: 検証器が止まった記録として通す（exit {v.returncode}: {(v.stdout + v.st… | 型紙 ×2 | test_scenarios_research.py::test_stopped_before_gates_reports[std-validator-accepts-stopped]<br>test_scenarios_research.py::test_stopped_before_gates_reports[heavy-validator-accepts-stopped] |  |
| 2881 | {th}: {k} は『飛ばした』と理由つきで残る——{g[k]} | 型紙・1 本以上（条件式の両腕で回数が違う） | test_scenarios_research.py::test_stopped_before_gates_reports[std-cold_reader-not-run]<br>test_scenarios_research.py::test_stopped_before_gates_reports[heavy-cold_reader-not-run]<br>test_scenarios_research.py::test_stopped_before_gates_reports[heavy-cartographer-not-run] |  |
| 2883 | 標準: cartographer はこの段では走らせない（飛ばしたと名乗らない）——{g['cartographer']… | 型紙・1 本以上（if の下に在る） | test_scenarios_research.py::test_stopped_before_gates_reports[std-cartographer-not-applicable] |  |
| 2885 | {th}: 突合の前に止まった rederiver は not_run で、暫定の判定は provisional に残る… | 型紙 ×2 | test_scenarios_research.py::test_stopped_before_gates_reports[std-rederiver-provisional]<br>test_scenarios_research.py::test_stopped_before_gates_reports[heavy-rederiver-provisional] |  |

#### simulate.test_unattended_stuck

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 446 | status が stopped |  | test_scenarios_research.py::test_unattended_stuck[status-stopped] |  |
| 447 | stopped_reason: {rec['convergence'].get('stopped_reason', ''… |  | test_scenarios_research.py::test_unattended_stuck[stopped-reason-unattended] |  |
| 448 | 要人間判断に stuck が載る |  | test_scenarios_research.py::test_unattended_stuck[human-items-stuck] |  |
| 449 | 停止でも報告は出る（検証器は stopped を通す） |  | test_scenarios_research.py::test_unattended_stuck[report-on-stop] |  |

#### simulate_review.test_awaiting

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 1385 | 主経路の観測: 見たと言う状態なのに観測した値が無ければ exit 1（本文の言い回しでなく欄で見る。{lied.get… |  | test_scenarios_review.py::test_awaiting[observed-empty] |  |
| 1387 | 主経路の観測: 空白だけの観測の行も観測した値に数えない（{lied.get('blank_err', '').stri… |  | test_scenarios_review.py::test_awaiting[observed-blank] |  |
| 1392 | 残る阻害が保留の問いだけになった周に聞く（{last.get('ask', {}).get('kinds')}） |  | test_scenarios_review.py::test_awaiting[asks-work-exhausted] |  |
| 1393 | 立った周（1）には聞かず、2 周目に聞く |  | test_scenarios_review.py::test_awaiting[asks-in-round-2] |  |
| 1395 | 答えを渡して続行 |  | test_scenarios_review.py::test_awaiting[answer-continue] |  |
| 1398 | 答えの後に収束（{last['status']}） |  | test_scenarios_review.py::test_awaiting[converges-after-answer] |  |
| 1400 | 3 周目に観測して問いは resolved |  | test_scenarios_review.py::test_awaiting[round-3-resolves] |  |
| 1401 | 人の答えが記録に残り次の周の judge に渡る |  | test_scenarios_review.py::test_awaiting[answer-kept-in-record] |  |

#### simulate_review.test_awaiting_origin_guards

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 1473 | 判定の時点: 人待ちの素材を出どころにする問いを台帳に載せない判定は拒む（rc={rc} {err.strip()[-1… |  | test_scenarios_review.py::test_awaiting_origin_guards[judge-unlisted] |  |
| 1476 | 判定の時点: 人待ちでない素材を出どころにした awaiting は拒み、field を案内する（rc={rc} {er… |  | test_scenarios_review.py::test_awaiting_origin_guards[judge-wrong-origin] |  |
| 1479 | 書いた時点: 人に諮っている欄を後の工程が clean で上書きすると拒む（rc={rc} {err.strip()[-… |  | test_scenarios_review.py::test_awaiting_origin_guards[ci-overwrite] |  |
| 1481 | CI を再実行する節のプロンプトに、この周の問いの台帳が渡る（人に諮っている欄を知って書ける） |  | test_scenarios_review.py::test_awaiting_origin_guards[ci-prompt-has-ledger] |  |
| 1483 | 実地の問いは field で台帳に載り、人待ちの CI の欄は awaiting_human のまま周の記録に入る（検証… |  | test_scenarios_review.py::test_awaiting_origin_guards[field-question-kept] |  |

#### simulate_review.test_ci_red_runaway

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 5646 | CI が赤のままの run は 5 周で止まる（{last['status']} r{run.state()['roun… |  | test_scenarios_review.py::test_ci_red_runaway[stops-at-round-5] |  |
| 5647 | 停止の理由が上限 |  | test_scenarios_review.py::test_ci_red_runaway[stop-reason-max-rounds] |  |

#### simulate_review.test_final_gate_empty_asks_human

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 6061 | 撃てた腕が 0 本の関門で収束を言わず人に諮る（{last['status']} {(last.get('ask') o… |  | test_scenarios_review.py::test_final_gate_empty_asks_human[asks-on-empty-gate] |  |
| 6063 | 諮る前に止めた理由（stop_reason）を立てる——stop や無人の停止でも理由が残る（{run.state()[… |  | test_scenarios_review.py::test_final_gate_empty_asks_human[stop-reason-before-asking] |  |
| 6067 | continue を返す（{r.stderr[-160:]}） |  | test_scenarios_review.py::test_final_gate_empty_asks_human[answer-continue] |  |
| 6069 | 人が認めた木なら、次の周の 0 本の関門で収束する（{last['status']}） |  | test_scenarios_review.py::test_final_gate_empty_asks_human[converges-next-round] |  |
| 6077 | 上限の周でも 0 本の関門は人に諮る（{(last.get('ask') or {}).get('kinds')}） |  | test_scenarios_review.py::test_final_gate_empty_asks_human[asks-at-max-round] |  |
| 6082 | 上限の周の continue は上限を 1 周だけ延ばし、答えの記録に延ばした値を書く（{st['max_rounds'… |  | test_scenarios_review.py::test_final_gate_empty_asks_human[continue-extends-by-one] |  |
| 6085 | 延ばした次の周で、同じ木の 0 本の関門が通って収束する（{last['status']}） |  | test_scenarios_review.py::test_final_gate_empty_asks_human[converges-after-extension] |  |

#### simulate_review.test_human_gate

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 6757 | 関所: 修正案の narrows が 1 件でもあれば、修正の前に人に聞く（{last.get('ask', {}).g… |  | test_scenarios_review.py::test_human_gate[narrows-ask-before-fix] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6761 | 関所: 人が答えるまで修正の節は出ない |  | test_scenarios_review.py::test_human_gate[no-fix-until-answered] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6762 | 関所: 方針の文書が無い run では、固定する版は無く、判定のプロンプトには方針の段落だけが出る |  | test_scenarios_review.py::test_human_gate[no-policy-document] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6765 | 関所: continue を返す（{r.stderr[-160:]}） |  | test_scenarios_review.py::test_human_gate[answer-continue] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6767 | 関所: 答えは人の答えの台帳（process.human_items）に残る（{hi}） |  | test_scenarios_review.py::test_human_gate[answer-in-human-items] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6770 | 関所: 人の答えの note が同じ周の修正役のプロンプトに届く |  | test_scenarios_review.py::test_human_gate[note-reaches-fix] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6775 | 修正の入口: 単位の行は記録の単位と同じ順で全部載り、義務の印を持つ（{[(r['key'][:20], r['owed… |  | test_scenarios_review.py::test_human_gate[fix-unit-rows] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6778 | 修正の入口: 判定の長い本文（母数の問いなど）は貼らず印だけを載せ、盤面に在る記録の置き場を指す（{refs}） |  | test_scenarios_review.py::test_human_gate[fix-long-bodies-not-pasted] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6781 | 関所: 修正差分の審査は後退の語を使えない（手直しの義務に入れて役に決めさせない。{seen.get('delta', … |  | test_scenarios_review.py::test_human_gate[delta-review-no-regression] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6783 | 関所: 方針の文書が init の後に変わった（役が書いた）なら、修正の後の関所で人に聞く（{last.get('ask… |  | test_scenarios_review.py::test_human_gate[policy-changed-asks] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6787 | 関所: 方針の文書の変化の行は差分のファイルの置き場を載せ（本文は載せない）、差分に変わった中身が在る（{row[-20… |  | test_scenarios_review.py::test_human_gate[policy-row-points-to-diff] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6791 | 関所: 通した方針の文書の変更は新しい版（写しも）を記録に固定し直し（以後の節は record.process.poli… |  | test_scenarios_review.py::test_human_gate[policy-refixed] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6806 | 関所: R4 の lost と方針とのぶつかり（policy_conflicts）は人に聞き、同じ文の行は通した後に聞き… |  | test_scenarios_review.py::test_human_gate[lost-and-conflict-asked-once] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6808 | 関所: 人が通した後は収束まで進む（{last['status']}） |  | test_scenarios_review.py::test_human_gate[converges] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 6820 | 関所: 事前審査が後退の穴を挙げたら、修正の前に人に聞く（{last.get('ask', {}).get('kinds… |  | test_scenarios_review.py::test_human_gate[plan-review-regression-asks] |  |
| 6824 | 関所: stop で run がその場で止まり、修正を出さない（{last.get('halted')}） |  | test_scenarios_review.py::test_human_gate[stop-halts-at-gate] |  |
| 6848 | 関所: --detail で直す義務の単位を外せる（義務に無い単位は拒んで盤面を変えず、受けた分は台帳に key で残る… |  | test_scenarios_review.py::test_human_gate[detail-excludes-unit] |  |
| 6852 | 関所: 外した単位は修正の側に見せる義務の印（fix_units の owed）からも外れる——修正の受け付けはこの印か… |  | test_scenarios_review.py::test_human_gate[excluded-unit-not-owed] |  |
| 6855 | 関所: 外した単位と理由が同じ周の修正役のプロンプトに届く |  | test_scenarios_review.py::test_human_gate[exclusion-reaches-fix] |  |
| 6862 | 関所: 無人では狭めの問いで止まり、修正を出さない（{st.get('halted')}） |  | test_scenarios_review.py::test_human_gate[unattended-stops] |  |

#### simulate_review.test_no_new_awaiting_after_judge

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 2483 | 判定の後の人待ち: 問いの無い awaiting_human を書いた p4.ci は拒む（{seen.get('err… |  | test_scenarios_review.py::test_no_new_awaiting_after_judge[p4-ci-awaiting-without-question] |  |

#### simulate_review.test_rejections

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 1650 | 返答の置き場のディレクトリは engine が作る（最初の波の節も、運び手が mkdir せずに書ける） |  | test_rejections_review.py::test_out_path_directories_are_made_by_the_engine |  |
| 1652 | 宣言の在るリポジトリでは、走らせるだけの節は engine が走らせる節（mode=engine_run）で出て、任せ先… |  | test_rejections_review.py::test_declared_checks_run_as_an_engine_run_node |  |
| 1656 | 任せ先: graph が delegate を宣言した回す側の節は ready に任せ先が載り、宣言の無い節には載らない… |  | test_rejections_review.py::test_undeclared_repo_falls_back_to_a_delegate |  |
| 1663 | 実在しない BASE は exit 1 |  | test_rejections_review.py::test_nonexistent_base_is_rejected |  |
| 1668 | 機械の節（作業ツリーの写し）は ready に出ない |  | test_rejections_review.py::test_machine_nodes_are_not_ready |  |
| 1669 | loop.py record は record.json の丸写し（直読みと同じ値。CLI の煙テストはここ 1 か所） |  | test_rejections_review.py::test_record_command_copies_record_json | 子プロセスで起こした loop.py record の標準出力の文字コードと終了コード（台本が CLI の煙を置く唯一の所） |
| 1674 | P1 の役が同じ波に並ぶ: {sorted(by)} |  | test_rejections_review.py::test_p1_roles_share_one_wave |  |
| 1675 | inspector は Read を持っても本文を貼る渡し方（ファイルの指示に従えの 1 文を拒むため）、investi… |  | test_rejections_review.py::test_inspector_gets_pasted_body_and_investigator_gets_a_path |  |
| 1680 | 今の周に走った節の素材が carried_over を名乗ると exit 1（rc={r.returncode}） |  | test_rejections_review.py::test_material_of_a_node_that_ran_cannot_claim_carried_over |  |
| 1683 | cold-reader には観点の節と差分本文だけが貼られ、目的は貼られない |  | test_rejections_review.py::test_cold_reader_prompt_has_lens_and_diff_but_no_purpose |  |
| 1685 | found なのに count が無い素材は exit 1（検証器の表で先に見る） |  | test_rejections_review.py::test_found_material_without_count_is_rejected |  |
| 1689 | investigator の instance の前後で作業ツリーが変わると exit 1 |  | test_rejections_review.py::test_worktree_change_around_an_investigator_is_rejected |  |
| 1692 | 順位（主経路）: 外部標準照合の done は、空の順位を付けられない理由なしで拒む（{r.stderr.strip()… |  | test_rejections_review.py::test_external_standards_without_rankings_none_is_rejected |  |
| 1700 | cli で起こした遮断系の done に --agent-id を渡すと exit 1（engine が起こす節に Ag… |  | test_rejections_review.py::test_agent_id_on_a_cli_node_is_rejected |  |
| 1708 | 既に変更済みのファイルの中身を差し替えても止まる: {str(nx.get('notes'))[:120]} |  | test_rejections_review.py::test_replacing_content_of_an_already_modified_file_stops |  |
| 1713 | P1 の前後で作業ツリーが変わると先へ進まない |  | test_rejections_review.py::test_worktree_change_across_p1_stops |  |
| 1716 | 同じ止まり方で next を叩き直しても git_mismatches は増えない |  | test_rejections_review.py::test_repeated_next_on_the_same_stop_does_not_grow_git_mismatches |  |
| 1722 | git が無い場では P1 の前後の突合が『測れない』で止まる（一致に倒さない） |  | test_rejections_review.py::test_without_git_the_p1_comparison_stops_as_unmeasurable |  |
| 1728 | 自分の変更なら next --accept-tree-change で通る: {str(nx.get('notes'))… |  | test_rejections_review.py::test_accept_tree_change_passes_the_comparison |  |
| 1730 | 受け付けた理由が git_mismatches に残る |  | test_rejections_review.py::test_accepted_reason_is_kept_in_git_mismatches |  |
| 1739 | 受け付ければ judge に進み、素材は 15 欄で渡る |  | test_rejections_review.py::test_after_acceptance_the_judge_runs_with_materials |  |
| 1742 | 台帳の出どころが無い judge の返答は exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[origin-not-in-units] |  |
| 1745 | split の出どころが [block] の返答は exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[split-origin-is-block] |  |
| 1749 | 先行例: 直す単位の行が欠けた judge の返答は exit 1（{r.stderr.strip()[-80:]}） |  | test_rejections_review.py::test_judge_reply_is_rejected[precedent-row-missing] |  |
| 1752 | 先行例: 出典の無い行は exit 1（{r.stderr.strip()[-80:]}） |  | test_rejections_review.py::test_judge_reply_is_rejected[precedent-without-source] |  |
| 1754 | 先行例: 見つからないなら何を探したかが要る（{r.stderr.strip()[-80:]}） |  | test_rejections_review.py::test_judge_reply_is_rejected[not-found-without-searched] |  |
| 1756 | 先行例: 同じ key の行が 2 つある judge の返答は exit 1（{r.stderr.strip()[-7… |  | test_rejections_review.py::test_judge_reply_is_rejected[precedent-key-duplicated] |  |
| 1759 | 先行例: 人へ回す問い（escalate）にも先行例の行が要る（{r.stderr.strip()[-80:]}） |  | test_rejections_review.py::test_judge_reply_is_rejected[escalate-needs-precedent] |  |
| 1764 | 先行例: 人へ回す問いに決まらない理由が無ければ exit 1（自明なので聞かない。{r.stderr.strip()[… |  | test_rejections_review.py::test_judge_reply_is_rejected[human-question-needs-undecided-because] |  |
| 1767 | judge の label が語彙外（blocker）なら exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[label-outside-vocabulary] |  |
| 1769 | 台帳の kind が語彙外なら exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[kind-outside-vocabulary] |  |
| 1771 | disposition が語彙外なら exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[disposition-outside-vocabulary] |  |
| 1773 | 台帳の status が語彙外なら exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[status-outside-vocabulary] |  |
| 1775 | judge の返答に知らない欄があれば exit 1（additionalProperties） |  | test_rejections_review.py::test_judge_reply_is_rejected[unknown-field] |  |
| 1777 | defer に reason の無い judge の返答は exit 1（以前の台本は defer を一度も返さず、この… |  | test_rejections_review.py::test_judge_reply_is_rejected[defer-without-reason] |  |
| 1781 | 一撃が閉じると見込む unit を名指ししない judge の返答は exit 1（効かなかったことを次の周が言えない） |  | test_rejections_review.py::test_judge_reply_is_rejected[one-shot-closes-empty] |  |
| 1783 | one_shot_closes が今の周の units に無い key を指すと exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[one-shot-closes-unknown-key] |  |
| 1786 | [block] に class_query（母数の問い）が無い judge の返答は exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[block-without-class-query] |  |
| 1788 | class_query.total が数でなければ exit 1 |  | test_rejections_review.py::test_judge_reply_is_rejected[class-query-total-not-a-number] |  |
| 1790 | 判定者の class_query も、走らせられない問いは exit 1（{r.stderr.strip()[-90:]… |  | test_rejections_review.py::test_judge_reply_is_rejected[class-query-unrunnable] |  |
| 1796 | defer の単位には母数を求めない（赤の理由は key の重複だけ。{r.stderr.strip()[-80:]}） |  | test_rejections_review.py::test_judge_reply_is_rejected[defer-needs-no-class-query] |  |
| 1810 | 正しい judge の返答は通り、どこから読んだかが返事に残る（stdin を cp1252 の環境で。rc={r.re… |  | test_rejections_review.py::test_judge_reply_from_stdin_is_accepted_and_says_where_it_was_read | PYTHONIOENCODING=cp1252 は Python の起動時にだけ効く——同じプロセスでは、標準入力をバイトで読んで UTF-8 に決める経路をcp1252 の既定で試せない（3 OS の通しで windows-latest だけ赤だった実測の腕） |
| 1812 | 標準入力の返答が置き場の古い返答より優先され、記録に入るのは新しい方 |  | test_rejections_review.py::test_stdin_reply_wins_over_a_stale_out_path |  |
| 1814 | 判定者の書いた件数は engine が数えた件数に置き換わり、置き換えたことが note と返事に残る（{cq0} / … |  | test_rejections_review.py::test_judge_count_is_replaced_by_the_engine_count |  |
| 1817 | engine が 0 件を数えた単位は置き換えず、0 だったことが note と返事に残る（{cq1} / {r.std… |  | test_rejections_review.py::test_zero_engine_count_is_not_substituted |  |
| 1820 | engine が 0 件を数えた単位の key は、判定の出口の欄（p2.diagnose の出力の engine_ze… |  | test_rejections_review.py::test_zero_count_unit_keys_are_left_for_the_fix |  |
| 1831 | [block] を直さない writer の返答は exit 1 で、残した理由を拒否文に併記する（{r.stderr.… |  | test_rejections_review.py::test_fix_leaving_a_block_unfixed_is_rejected_with_its_reason |  |
| 1837 | 閉鎖の実証で赤を見ていないのに fix_closure=clean の返答は exit 1（rc={r.returnco… |  | test_rejections_review.py::test_clean_closure_without_red_seen_is_rejected |  |
| 1839 | 修正が在るのに fix_closure=not_applicable の返答は exit 1（changes が非空とい… |  | test_rejections_review.py::test_fix_reply_is_rejected[not-applicable-closure-with-changes] |  |
| 1842 | 2 つ以上の修正が触った面を書き落とすと exit 1（機械が files から面を出す） |  | test_rejections_review.py::test_fix_reply_is_rejected[interactions-left-out] |  |
| 1844 | 面ごとの修正の一覧（changes）は役に書かせない——書けば型で拒む（写しの入口を残さない） |  | test_rejections_review.py::test_fix_reply_is_rejected[interactions-listing-changes] |  |
| 1846 | 干渉を突き合わせた結果が空同然なら exit 1（bypass_tried と同じ空語検査） |  | test_rejections_review.py::test_fix_reply_is_rejected[interactions-checked-empty-word] |  |
| 1849 | 修正を残したまま破りに行った形跡が無い返答は exit 1 |  | test_rejections_review.py::test_fix_reply_is_rejected[bypass-not-tried] |  |
| 1851 | 壊しうる面を確かめた結果が空同然なら exit 1 |  | test_rejections_review.py::test_fix_reply_is_rejected[breaks-result-empty-word] |  |
| 1853 | 症状を塞ぐ修正に「なぜ今それで止めるか」が無ければ exit 1 |  | test_rejections_review.py::test_fix_reply_is_rejected[symptom-without-why-now] |  |
| 1862 | 判定者が class_query を持つ単位は coverage を省いても coverage では拒まない（赤の理由は… |  | test_rejections_review.py::test_fix_reply_is_rejected[coverage-omitted-under-judge-query] |  |
| 1867 | coverage に remaining だけを書いた返答も coverage では拒まない（赤の理由は wrote_r… |  | test_rejections_review.py::test_fix_reply_is_rejected[coverage-remaining-only] |  |
| 1872 | 母数 2 のうち閉鎖を実証した site が 1 件で残りが在るのに remaining が無ければ exit 1（母数… |  | test_rejections_review.py::test_fix_reply_is_rejected[partial-closure-without-remaining] |  |
| 1874 | 1 行のコマンドの how は型で拒む（欄で書く。{r.stderr.strip()[-90:]}） |  | test_rejections_review.py::test_fix_reply_is_rejected[how-as-one-command] |  |
| 1876 | 走らせられない how は拒む（当たらないパス。{r.stderr.strip()[-90:]}） |  | test_rejections_review.py::test_fix_reply_is_rejected[how-unrunnable] |  |
| 1881 | 覆い: 判定者の母数より狭い how は理由なしで拒む（{r.stderr.strip()[-70:]}） |  | test_rejections_review.py::test_fix_reply_is_rejected[how-narrower-than-judge] |  |
| 1883 | 覆い: 空語（『なし』）の remaining は理由に数えない（{r.stderr.strip()[-70:]}） |  | test_rejections_review.py::test_fix_reply_is_rejected[remaining-empty-word] |  |
| 1886 | 先行例: 修正の先行例に出典が無ければ exit 1（{r.stderr.strip()[-80:]}） |  | test_rejections_review.py::test_fix_reply_is_rejected[fix-precedent-without-source] |  |
| 1891 | 先行例: 判定者の行が在る単位は from_judge_row で採れる（赤の理由は wrote_refs だけ。{r.… |  | test_rejections_review.py::test_fix_reply_is_rejected[fix-precedent-from-judge-row] |  |
| 1895 | closure.sites が母数を超える返答は exit 1（問いが対象を取りこぼしている） |  | test_rejections_review.py::test_fix_reply_is_rejected[closure-sites-over-population] |  |
| 1906 | リンク: 申告が空でも、差分が足したリンクの指し先と見出しを引いて拒む（コードスパンの中は拾わない。{r.stderr.… |  | test_rejections_review.py::test_fix_reply_is_rejected[markdown-links-added-by-the-diff] |  |
| 1913 | 残した理由を書けば部分的な覆いは通る（赤の理由は wrote_refs だけ。{r.stderr.strip()[-70… |  | test_rejections_review.py::test_fix_reply_is_rejected[partial-coverage-with-remaining] |  |
| 1917 | 指し先に無い字列は exit 1（どこかに在るかでなく、指し先に在るかを見る。rc={r.returncode}） |  | test_rejections_review.py::test_fix_reply_is_rejected[cite-not-in-target] |  |
| 1922 | 指し先のファイルが無ければ exit 1（『中に無い』とは別の拒否文。{r.stderr.strip()[-90:]}） |  | test_rejections_review.py::test_fix_reply_is_rejected[cite-target-missing] |  |
| 1926 | wrote_refs を落とした返答は型で拒まれる（必須の欄） |  | test_rejections_review.py::test_fix_reply_is_rejected[wrote-refs-dropped] |  |
| 1931 | 別のファイルに同じ字列が在っても、target に無ければ exit 1（rc={r.returncode}） |  | test_rejections_review.py::test_fix_reply_is_rejected[same-text-in-another-file] |  |
| 1934 | 改行を含む cite は exit 1（修正側には 1 行 1 件の規律だけを言い、指摘側の git grep の理由を… |  | test_rejections_review.py::test_fix_reply_is_rejected[cite-with-newline] |  |
| 1952 | 修正前の母数 1・修正後に engine が数えた 0 が記録に残る（拒否には使わない。rc={r.returncode… |  | test_rejections_review.py::test_coverage_before_and_after_are_recorded |  |
| 1955 | 赤を見た修正と見ていない修正（文書）が混じる周の clean は通る——周の全体で見る。返答は out_path から読… |  | test_rejections_review.py::test_mixed_closure_passes_and_reads_the_out_path |  |

#### simulate_review.test_runaway

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 1493 | 5 周で停止（{run.state()['round']}） |  | test_scenarios_review.py::test_runaway[stops-at-round-5] |  |
| 1494 | 停止の理由が上限 |  | test_scenarios_review.py::test_runaway[stop-reason-is-the-cap] |  |

#### simulate_review.test_stop_after_round

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 4160 | init が --stop-after-round を受ける（{run.init.stderr[-200:]}） |  | test_scenarios_review.py::test_stop_after_round[init-accepts] |  |
| 4163 | 1 周目の締めの後の next が stopped と halted（by=stop_after_round）を返す（{… |  | test_scenarios_review.py::test_stop_after_round[stops-after-round-1] |  |
| 4165 | 周の締め（周の記録・converge）は済み、2 周目は開いていない（round {st['round']}・周 {le… |  | test_scenarios_review.py::test_stop_after_round[round-closed-not-opened] |  |
| 4168 | 止めた後の next は節を出さず、止めた口を言う（{nx.get('note')}） |  | test_scenarios_review.py::test_stop_after_round[next-after-stop] |  |
| 4171 | status に halted と stop_after_round が出る（{s.get('halted')}・{s.… |  | test_scenarios_review.py::test_stop_after_round[status-shows-halted] |  |
| 4175 | 仕上げた記録に止めた理由が残る（{proc.get('outcome')}・{proc.get('stop_reason… |  | test_scenarios_review.py::test_stop_after_round[finalized-reason] |  |
| 4178 | 止めたことは trace にも 1 行残る（{halts}） |  | test_scenarios_review.py::test_stop_after_round[trace-has-one-halt] |  |
| 4184 | resume が 2 周目を開き、1 周目の試行はそのまま（{r.stderr[-300:]}・周 {st['round… |  | test_scenarios_review.py::test_stop_after_round[resume-opens-round-2] |  |
| 4188 | 続けた run は新しい止め周（2 周目）の締めで止まり、続けた痕跡が盤面に残る（{st.get('halted')}・… |  | test_scenarios_review.py::test_stop_after_round[resumed-stops-at-round-2] |  |
| 4192 | 続けた痕跡は記録の process.resumes にも写る（halted は最後の止めだけになるので） |  | test_scenarios_review.py::test_stop_after_round[resumes-in-record] |  |
| 4199 | --stop-after-round 2 は 1 周目の後は次の周を開き、2 周目の締めの後で止まる（周 {len(st… |  | test_scenarios_review.py::test_stop_after_round[stop-after-2] |  |
| 4207 | answer continue でも次の周を開かずに止まる（{r.stdout[-160:]}{r.stderr[-16… |  | test_scenarios_review.py::test_stop_after_round[answer-continue-also-stops] |  |
| 4213 | --stop-after-round 0 は init が拒み、盤面を残さない（{run.init.stderr[-16… |  | test_scenarios_review.py::test_stop_after_round[zero-rejected-at-init] |  |

#### simulate_review.test_stop_midround

| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |
|---|---|---|---|---|
| 4071 | 止める: 理由の空は拒む（{r.stderr[-120:]}） |  | test_scenarios_review.py::test_stop_midround[empty-reason] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4075 | 止める: 宣言の在る graph では halted にせず報告へ進む（{r.stdout[-200:]}{r.stde… |  | test_scenarios_review.py::test_stop_midround[declared-graph-goes-to-report] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4078 | 止める: 待ちの節は止めた印（省いた印と別）になる（{sorted(rd['stopped'])[:5]}） |  | test_scenarios_review.py::test_stop_midround[pending-node-marked-stopped] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4081 | 止める: 止めた周の記録は、走らなかった R と素材を止めた事実で書く（{{k: v['status'] for k, … |  | test_scenarios_review.py::test_stop_midround[round-record-says-stopped] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4084 | 止める: 止めた時点で記録に理由が入る（報告の節が読む） |  | test_scenarios_review.py::test_stop_midround[reason-in-record] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4089 | 止める: 止めた節の返答は受け付けない（{r.stderr[-120:]}） |  | test_scenarios_review.py::test_stop_midround[late-reply-rejected] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4091 | 止める: 止まった run は二度止めない（{r.stderr[-120:]}） |  | test_scenarios_review.py::test_stop_midround[no-second-stop] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4093 | 止める: 次の next は報告の節だけを出す（{[i['node'] for i in nx['ready']]}） |  | test_scenarios_review.py::test_stop_midround[next-is-report-only] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4096 | 止める: 報告まで届き、仕上げた記録に止めた口と止めた節が残る（{proc.get('stop_reason')}・{p… |  | test_scenarios_review.py::test_stop_midround[reaches-report] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4107 | 止める: 残ったファイルを済んだと読まず、盤面から周の記録を組み直す（{r.stderr[-160:]}{sorted(… |  | test_scenarios_review.py::test_stop_midround[stale-round-file] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4118 | 止める: 2 周目の判定より前なら前の周の単位と台帳を報告に残す（{r.stderr[-160:]}） |  | test_scenarios_review.py::test_stop_midround[stop-before-round-2-judge] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4130 | 止める: 人に聞いている最中なら、答えないまま外した問いを記録（halted と要人間判断の欄）に残す（{r.stder… |  | test_scenarios_review.py::test_stop_midround[stop-while-asking] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4148 | 止める: 宣言の無い graph は halted（by=stop）で後の節を出さない（{r.stdout[-160:]… |  | test_scenarios_review.py::test_stop_midround[undeclared-graph-halts] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
| 4151 | 止める: halted の run は『もう止まっている』で拒む（{r.stderr[-120:]}） |  | test_scenarios_review.py::test_stop_midround[halted-run-refuses-stop] | 通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手 |
<!-- ledger:end -->
