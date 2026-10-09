<!-- coldwrite:skip 内部の設計書。語は works/docs/concepts.md の「語」の節で定義 -->
# 返答の足し欄（marks）の住処を 1 つにする（実装計画）

状態: 計画と実装を同じ枝 `wip/marks-home` で行う。版は上げない。

> **実装する者へ:** superpowers:executing-plans で Task ごとに進める。手順は `- [ ]` で追う。

**目的:** 「写しの graph の型は欄を持てないので、役の型にだけ欄を足し（足す）、受け付けが盤面へ渡す前に外し（外す）、盤面のファイルに置き（置く）、後で読み戻す（読む）」の手順を、1 つのモジュール `.shared/core/marks.py` に住まわせる。各モジュールには欄の意味（欄の型・欠けと誤りの検査・控えの中身の形・読んだ後の使い方）だけを残す。

**作り:** `marks.py` は種（kind）の表 `KINDS` を持つ。1 行は「節（か役）→ 行の在り処（型と返答で同じ道）」・盤面のファイルの名・置き場（盤面の根か今の周の作業の置き場）。手順の口は `add`（足す）・`split`（外す）・`path_of`（置き場のパス）・`write`（一時のファイルから os.replace で置く）・`load`（読めなければ None）。欄の型と名は意味なので各モジュールが渡す。

**道具:** Python 3（標準ライブラリだけ）・unittest。

**仕様:** `works/docs/concepts.md` の `marks` の行と、この計画の 1 節。

## 1. 今の姿（手順ごとに、誰が何を書いているか）

| モジュール | 足す | 外す | 置く | 読む |
| --- | --- | --- | --- | --- |
| gatemarks | 行に手書き | 手書き | 根・直に書く | 手書き |
| planmarks | 行に手書き | 手書き | 根・原子的 | 手書き |
| deltamarks | 頭に手書き | 手書き | 作業・原子的 | 手書き |
| converge | 頭に手書き | 手書き 3 本 | 往復の控え | 往復の控え |
| querytest | 行に手書き | 手書き | 根・直に書く | 手書き |
| outpurpose | 頭に手書き | 手書き | 根・原子的 | 手書き |
| prcheck | 頭に手書き | 手書き 2 か所 | 作業・原子的 | 読まない |

地図の行は 4 つ（gatemarks・planmarks・deltamarks・converge）を挙げるが、調べると querytest・outpurpose・prcheck も同じ 4 段を手で書いている（7 か所）。ほかに修正役の欄（`recount.fix_output_format` が足し、`blk-fix` の受け付けと並べの枝が外す）と報告の書き手の `terms`（`blk-report/lib/report_roles.py`）も同じ手順を持つが、並行の作業が触っている所なので今回は動かさず、柵の既知の漏れに理由つきで置く。

各モジュールに残す物（意味）と、`marks` へ移す物（手順）:

- gatemarks: 残す＝決め手の欄の型・`narrow_gaps`・`recommend_gaps`・控えの形 `{節: {round, marks}}`・空なら節の分を消す決まり。移す＝行の道（`plan[].narrows[]`・`faces[]`）・欄の足し方・外し方・ファイルの名・書き方・読み方
- planmarks: 残す＝欄の型・`gaps`・外した欄に足す `unit_keys`・`adds`・`limit`・凍結の印（sha256 の trace）・`amended`。移す＝行の道 `plan[]`・足し方・外し方・ファイルの名・原子的な書き方・読み方
- deltamarks: 残す＝2 判定の型・`gaps`・trace の行。移す＝足し方・外し方・ファイルの名・書き方・読み方
- converge: 残す＝欄の型・往復の控え（`plan-converge.json` は壁打ちの記録で、足し欄の控えではない。置く・読むは移さない）。移す＝足し方と外し方（`split`・`tree_split`・`drop_fields`）
- querytest: 残す＝例の型・`problems`・`unproven` の印・控えを鍵で重ねる決まり・`restore`。移す＝行の道 `units[].class_query`・足し方・外し方・ファイルの名・書き方・読み方
- outpurpose: 残す＝行の型・`problems`・控えの形 `{rounds}` と読めない時の誤り。移す＝足し方・外し方・ファイルの名・書き方
- prcheck: 残す＝欄の型・`check_excluded`・控えの形。移す＝足し方・外し方・ファイルの名・書き方

振る舞いの約束: 盤面のファイルの名と中身の形は変えない。直に書いていた 2 つ（gatemarks・querytest）は一時のファイルから置き換える書き方にそろう（中身は同じ。途中で落ちても半端なファイルが残らない）。

## Task 1: 住処 `marks.py` と試験

**Files:** Create `.shared/core/marks.py`・`tests/test_marks.py`。Modify `tests/test_layers.py`（`marks` を L1 に）・`tests/tiers.py`（fast に）

**Interfaces（後の Task が使う）:**
- `KINDS: dict[str, Kind]`、`Kind(at: dict[str, tuple], file: str | None, place: str)`、`EACH = "[]"`、`ROOT`・`WORK`
- `nodes(kind) -> tuple`
- `add(kind, node, schema, fields: dict, required=()) -> dict`（節が表に無ければ渡した物をそのまま返す）
- `drop(kind, node, schema, names) -> dict`（add の逆。審査の受け付けが欄を外した返答を写しの型で照らす時。`.shared/core/refix.py` が手で逆をしていた所を `deltamarks.without_verdicts` 経由で寄せる。審査の後に足した）
- `rows(kind, node, reply)`（欄を持つ行をその場のまま道の形で。gatemarks の検査が行を名指す）
- `split(kind, node, reply, names) -> (bare, got)`（got は道の `EACH` の段だけ入れ子の並び、葉は外した欄の dict。節が表に無ければ（写し, None））
- `path_of(kind, board) -> pathlib.Path`（ROOT は `board.dir` か渡したパス、WORK は `board.work(名)`）
- `write(path, doc) -> bytes`（一時のファイルを消してから書き、os.replace。置いたバイトを返す）
- `load(path)`（読めない・無い・JSON でなければ None）

- [ ] 試験を書く: 表のファイルの名がいまの 6 つのまま・`add` の道（頭・行・入れ子の行）と required の重なりを足さない・`split` が元を変えず、形の崩れた返答（dict でない・並びでない）で落ちない・`write` が一時のファイルを残さずリンクの先へ書かない・`load` の None
- [ ] 落ちるのを見る → `marks.py` を書く → 通るのを見る → commit

## Task 2: 7 つのモジュールを住処に寄せる

**Files:** Modify `.shared/core/{gatemarks,planmarks,deltamarks,converge,querytest,outpurpose,prcheck}.py`

- [ ] 1 つずつ寄せ、そのモジュールの既存の試験（網）を回す: gatemarks → `test_gate_drafts`・`test_plan_gate`、planmarks → `test_plan_fields`、deltamarks → `test_delta_marks`、converge → `test_converge`、querytest → `test_accept`・`test_blk_judge`、outpurpose → `test_out_of_purpose`、prcheck → `test_blk_pr`
- [ ] fast の段・`dev/check.sh`・重い段はモジュールごと（`test_blk_plan`・`test_replan`・`test_blk_tests_delta`・`test_blk_refix`・`test_report` など）→ commit

## Task 3: 地図と柵

**Files:** Modify `docs/concepts.md`（`marks` を住処ありに）・`docs/concepts.json`・`CHANGELOG.md`

- [ ] 柵 1: 盤面のファイルの名（6 つ）の字は住処・宣言（`manifest.json`）・約束（`schemas/*.schema.json`）の外に書かない
- [ ] 柵 2: 役の型に欄を手で足す・外す形（`["properties"][…] =`・`["properties"].update(`・`.pop(`・`setdefault("properties"`）
- [ ] 柵 3: 返答から欄を手で外す形（`for k, v in reply.items() if k`・`reply.pop(`・`.pop(k) for k in`）。柵 2・3 の既知の漏れは修正役の欄と報告の `terms`（理由つき）。前の 7 つのモジュールはどれも柵 2 か 3 に当たる（審査で確かめた）
- [ ] `test_concept_fences` を緑に → commit

## Review Focus

- 形の崩れた返答（`plan` が並びでない・`faces` が文字列・返答が dict でない）: 落ちずに空の欄を返す（Task 1 の試験）。前は文字列・dict の中身を 1 字・1 鍵ずつ辿って空の欄を並べたが、受け付けの前段（`rolekit.parse_reply`・`planblk._plan_malformed`・`replan._malformed`）が形の崩れた返答を先に拒むので、run の動きは同じ
- 盤面のファイルがリンクのとき: 置き換えはリンクを置き換え、先を書かない（Task 1）
- 欄が 1 つも無い返答: gatemarks は控えを作らない・消す、outpurpose は控えが無ければ作らない（既存の試験）
- 前の版の盤面（ファイルの名と中身の形）: 名と形は変えないので読める（既存の試験と fixture）
- 役の型の欄の並び: 足した欄の順が前と同じ（`test_blk_plan` の output_format の一致・`test_blk_pr`）
