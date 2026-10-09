<!-- coldwrite:skip 内部の設計書。語は「語」の節と works/README.md で定義 -->
# 頼まれたら何周もつなげる（run を周ごとに鎖でつなぎ、差分 1 本と報告 1 本で返す）

## 平たく言うと（3 行）

- 何の話か: works は今、1 回起こすと 1 周で止まる。2 周目が欲しい利用者は、前の差分を手で当てて起こし直していた。持ち主の決め「指定があれば何周もつなげれるようにしたい」（2026-10-09）を、どう作るかの計画。
- 分かったこと: 1 本の run の中で周を回す形（棚上げの線 B）は、Archon の関所と輪の決まりに当たり、作りかけで止まっている。推しは、起動の殻が「前の周の結果の版」と「前の周が書いた次の依頼」で次の run を起こす外の鎖。どの周も今と同じ 1 本の run で、入口の形も変わらない。先に、散らばった持ち越しの考えを 1 つのモジュールにまとめる（Task 1）。
- 頼みたいこと: 7 節の 2 件の決め（どちらも推しつき）。ほかは推しで進める。

状態: 計画だけ（コードは変えていない）。2026-10-09、版 0.2.53（main の b23eefa9）の事実で書いた。計画 `docs/plans/2026-10-09-clean-whole.md`（以下「全体の計画」）の 6 節の「周を重ねる線はやらない」と、段 5 の持ち越しの順を直す（8 節）。

> **実装する者へ:** superpowers:subagent-driven-development（推し）か superpowers:executing-plans で、Task ごとに回す。下請けは全部 opus。手順は `- [ ]` で追う。

**目的:** 利用者が `use.sh start --rounds N` と打てば、works が周を自分でつなぎ、止まる条件に当たるまで回し、全部の周をまとめた差分 1 本と報告 1 本を返す。打たなければ今と同じ 1 周。

**作り:** 線（`darkfactory/darkfactory.yaml`）と写しの核は変えない。各周は今と同じ 1 本の run。周の間の決め（次を起こすか・次の依頼・止めの理由）は core の新しいモジュール `chain.py` が持ち、起動の殻 `dev/use.sh` は鎖の控えに従って次の run を起こすだけ。持ち越しの形（次の依頼の欄・下書きの印・前の失敗の置き場）は先に 1 つのモジュール `carry.py` にまとめる。

**道具:** Python 3.12（`carry.py` は `ghreads.py` と同じく 3.9 で動く形・標準ライブラリだけ）・unittest・POSIX sh・git・Archon v0.11.1。

**仕様:** この文書の 3〜6 節。

## 1. 今の姿（事実。行は b23eefa9）

- 1 周で止める: `.shared/core/entry.py:1212` の `begin(..., stop_after_round=1, ...)`。2 周目は回らず、残りが在れば結末は round_limit
- 次の run への持ち越しは書き手と読み手が別々に持つ（考えの住処の地図 `docs/concepts.md` の `carry-over`。状態は散らばり）
  - 書き手: `.shared/core/report.py:131` `NEXT_REQUEST_FILE`・`:608` `prior_failures`・`:671` `next_request`・`:1718` `next_doc`
  - 読み手と形の確かめ: `.shared/core/ghreads.py:47-50` `KEYS`・`ANSWER_KEYS`・`DRAFT_KEYS`・`PRIOR_KEYS`、`:68` `request_parts`、`:112` `carry_ci`
  - 盤面へ置く: `.shared/core/entry.py:995` `PRIOR_IN_FILE`・`:1035` `place_prior`・`:1041` `prior_section`
  - 答えの下書き: `.shared/core/gatemarks.py:584` `answer_drafts`
- 依頼の答えが問いに当たる道は 1 本だけ: `gatemarks._hits`（`:520`）が、答えの `question` と台帳の問いの key か出どころ origin の字の一致を見る。問いの key は判定役がその run で作るので、依頼を書く時の利用者は key を知らない。当たらなかった答えは `unmatched_answer_lines`（`:620`）が報告に「当たる問いが台帳に無い」と並べるだけ。利用者が「自分で書いた確かめの項目に答えを結べなかった」と言った件はこの形（この文書は「確かめの項目」を、依頼に自分で書いた findings の行と読む。4.5 の仕組みは問いの key でも findings の行でも同じに結ぶ）
- 前の run の下書きの答えも同じ穴を持つ: `_ask_draft` は前の run の問いの key を `question` に置くが、次の run の判定役が同じ key を作る保証は無い
- 2 周目の今の手順（利用者 work4 の run 97fd532f は 2 周目）: `use.sh apply` で前の差分を手元に当てる → `next-request.json` を見直して依頼にする → `use.sh start` で起こし直す
- 1 周の重さ: 小さな見本で約 20 分・$7.7。canary の run 5318f732（依頼だけ・P1 の役なし）は 14.2 分・$5.68、e91112dd（差分あり・P1 の局所レビューあり）は 23.4 分・$8.11
- 線 B（1 本の run の中で周を回す入口 `darkfactory-rounds`）は棚上げ。枝 `wip/works-trackB` は 21 commit で 2026-09-27 から止まっている（計画 `docs/plans/2026-09-27-darkfactory-rounds.md` の 18 Task のうち T7 の途中まで）

## 2. 語

- 周: 判定 → 修正 → 審査 → 報告の 1 回り。今は 1 run＝1 周
- 鎖（chain）: 1 回の `use.sh start --rounds N` が起こす、周ごとの run の並び。id は `c-<日時>-<pid>`
- 周の基 `base_k`: k 周目の run を切った版。1 周目は今の `use.sh start` が作る版（対象の HEAD か、手元の変更を包んだ commit）
- 周の結果 `result_k`: `base_k` に k 周目の差分（`use.sh show` が書く `run-<id>.diff`）を当てた木の commit。親は `base_k`
- 元の基: 1 周目の `base_k`。利用者に返す最後の差分は「元の基 → 最後に採った周の結果」
- 鎖の控え: `<利用の家>/chains/<鎖の id>/chain.json`（5 節）。利用の家は `use.sh` の `WORKS_USE_HOME`
- 4 つの軸: 全体の計画の決め 1。関所の項目を run の中で決めてよいのは、自明か・汚くないか・世界の解か・やりすぎでないか、の 4 つが全部満たされた時だけ

## 3. 案の比べ

### 3.1 3 つの案

- (a) 線の中の輪: 線 B・C を 1 本の Archon の run の中に戻し、`loop_group` で周を回す
- (b) 外の鎖: 起動の殻が、前の周の結果の版を基にし、前の周の `next-request.json` を依頼にして、次の run を今と同じ入口で起こす
- (c) そのほか: (c1) 線の中の節が `archon workflow run` で子の run を起こす。(c2) 会話の運び役（工場の外の AI）が周をつなぐ

| 観点 | (a) 線の中の輪 | (b) 外の鎖 | (c1) 子の run | (c2) 運び役 |
| --- | --- | --- | --- | --- |
| 関所の決まり | × | ◯ | × | ◯ |
| resume | △ | ◯ | × | ◯ |
| worktree | ◯ | ◯ | △ | ◯ |
| 1 つの入力の形 | △ | ◯ | ◯ | ◯ |
| 1 run＝1 周の決め | × | ◯ | ◯ | ◯ |
| 持ち越しの住処 | △ | ◯ | ◯ | × |
| 費用の見え方 | △ | ◯ | × | △ |
| 周ごとの重さ | ◯ | △ | △ | △ |
| works の中の仕組みか | ◯ | ◯ | ◯ | × |
| 作る量 | 大 | 小 | 中 | 無 |

各行の訳:

- 関所の決まり: 線の関所は 4 つ（`darkfactory.yaml` の 96・465・669・1138 行の approval）で、全部が輪の外の最上段に在る。works の YAML の決まり（`tests/test_yaml_rules.py:44`）は輪の本体に approval を置くことを拒む。Archon の再開は、本体が関所で終わる輪で止まった回の会話を継がない（`docs/archon-feedback.md` の 26）。(a) は 4 つの関所を周ごとの唯一の末端の関所へ作り直すことになり、線 B が 18 Task を要した訳の多くがここ。(c1) は子の run の関所に親から答える道が無い
- resume: Archon v0.11.1 の resume は輪を 1 周目から回し直し、本体を全部回し直す（`docs/archon-feedback.md` の resume の行）。(a) では 3 周目で落ちた run の resume が、ブロックの中の約 47 の `loop_group` の冪等さに頼る。(b) は周ごとの run が今の resume をそのまま使う
- 1 つの入力の形: (b) の次の周は「基の版・差分・依頼の行」の形の普通の入力で、新しい入口の種を作らない（計画 `docs/plans/2026-10-09-one-entry-shape.md`）。(a) は周の輪の入口を別に持つ（線 B の `darkfactory-rounds`）
- 1 run＝1 周の決め: 持ち主の観点 `carry`「同じ run で 2 周目を回さず、…次の run の依頼にする」と `request-to-judge`「2周目はかけずに別のrunで修正する」（観点の地図 `docs/owner-decisions.md`）。(b) はこの決めを守ったまま周をつなぐ
- 持ち越しの住処: (b) は周の間を `next-request.json` の形だけで渡すので、持ち越しの考えを 1 か所にまとめれば足りる。(a) は盤面の中で周を渡すので、持ち越しの形と別に周の記録の形が要る。(c2) は持ち越しを AI の判断に任せる
- 費用の見え方: (b) は周ごとに 1 本の run なので、今の報告の費用の節がそのまま周ごとの数になる
- 周ごとの重さ: (b) は周ごとに P0（修正前の CI・前提・目的・並行 PR）を回し直す。量は Task 9 で測る。減らす道は 12 節の 3
- works の中の仕組みか: (c2) は今の手での 2 周目を AI がやるだけで、仕組みとして残らない（持ち主「観点は works の中の仕組みに」）

**推し: (b) 外の鎖。** 訳: 関所・resume・worktree の Archon の決まりに 1 つも当たらず、線と写しの核を変えない。持ち主の「1 run＝1 周」と「入口は 1 つの入力の形」を両方守る。周ごとの費用がそのまま見える。(a) が勝つのは周ごとの P0 の費用だけで、それは測ってから減らせる（12 節の 3）。

### 3.2 次の周の差分の根（(b) の中の選び）

- B1: 次の周の基も差分の根も `result_k`。差分は空で、判定から入る（P1 の役を起こさない）
- B2: 次の周の run は `result_k` から切り、差分の根は `base_k`（入力 `base=base_k`）。差分は k 周目の直しそのもので、P1 の役が前の周の直しを審査し、残りの依頼の行は判定に届く

**推し: B2。** 訳: review-graph の 2 周目は、1 周目の直しに P1 を回す（写しの核の `entry_first_fix`。差分が空で始めた run の、最初に修正が入った次の周）。持ち主の観点 `independent-verdict`「修正があった周も、直した後にその修正がよかったかを確かめる」。B1 は review-graph より能力が下がる。費用の差は canary の 2 本の差（約 9 分・約 $2.4）が目安。

## 4. 形

### 4.1 打ち方（既定は今と同じ 1 周）

```
use.sh start --rounds N [--budget-usd X] [--base <版> | --pr <番号>] [--] [<対象>] <依頼の JSON か -> [<test_cmd> [<tdd_suite>]]
```

- `--rounds` を付けなければ今と同じ（鎖の控えを作らない）。`--rounds 1` も同じ
- `N` は 2 以上の整数。works が決める上限は置かない（持ち主「根拠の無い上限を置かない」。N は利用者が名指した数）
- `--budget-usd X` は任意。既定は無し（上限は利用者が決めた時だけ）
- 拒む組（Archon を起こす前に 1 行で）: `WORKS_DESIGN_ONLY=1`（差分を作らないので 2 周目の基が無い）・`WORKS_USE_FIX_FIXTURE`（固定材料は 1 周目の修正の直前の盤面）
- 無人（`WORKS_USE_UNATTENDED=1`）とも組める。止まり方は 4.3 の 4
- 鎖の 2 周目からの入力は、1 周目の入力（test_cmd・tdd_suite・`WORKS_USE_*` の値）を鎖の控えから写す。周ごとに変えない

### 4.2 1 周の終わりに殻がすること

殻（`dev/use.sh`）が run の終わりを見る所は 2 つ: `start` の終わり（前景で回り、終わるか関所で止まる）と `wait`（`answer`・`approve`・resume の後の run を待つ）。どちらも、run の控えが鎖に属していれば、次を 1 回呼ぶ。

1. run が関所で待つ（paused）か、落ちた（failed）: 何もしない。人が `answer` か resume をし、`wait` が終わりを見た時にまた来る
2. run が終わった: `use.sh show` が今どおり `run-<id>.diff` を書く
3. 周の結果を作る: 一時の index に `base_k` の木を読み、`run-<id>.diff` を `git apply --cached --binary` で当て、`write-tree` と `commit-tree -p base_k` で `result_k` を作り、参照 `refs/works/chains/<鎖>/<k>` で守る。worktree を読まないので、`show` が片付けた後でも作れる
4. 周の行を鎖の控えに書く（5 節の `rounds[]`）
5. 決める: `python3 chain.py verdict <鎖の控え>` → `go`・`wait`・`stop` と理由
6. `go` なら次の依頼を書き（4.4）、次の run を `--from result_k --input base=base_k --input request=<次の依頼> --input launch_mark=<鎖>-<k+1>` と 1 周目と同じ入力で起こし、1 に戻る。起動の印を必ず付けるので、依頼が空の周（4.3 の決め 1）でも run を結べる
7. `stop` なら鎖の報告（4.6）と最後の差分（4.7）を書き、行を出して終わる

周の境で出す 1 行の例: `周 2/3 を起こす（前の周 21 分・$7.70、累計 $7.70、上限 なし）`

### 4.3 止める条件（決まった順に見る）

1. 周の数: k が N に達した → `rounds_reached`
2. 結末の種（結末の住処 `report.OUTCOMES` に新しく足す種の表 `OUTCOME_KIND`。4.8）:
   - `closed`（fixed・no_fix_needed）→ `closed`。ただし 7 節の決め 1 で「確かめの周を足す」を採れば、fixed で周が残る時は依頼の行を空にして 1 周足す（差分は k 周目の直し・依頼なし＝今の「変更だけ」の run）
   - `halted`（止め札・人が関所で stop・ラインの止め・記録が検証器を通らない）→ `halted`
   - `waiting`（needs_human）→ `needs_human`
   - `broken`（interrupted）→ `wait`（resume と `wait` の後に続く）
   - `open`（round_limit）→ 次の 3〜6 を見る
3. 人の判断が要る: k 周目の `next-request.json` に下書きの印の在る行（`answers` の下書き、目的の外の findings）が在る → `needs_human`。関所の項目を run の中で決めるかは 4 つの軸の仕組み（全体の計画の段 2 の Task 2.6）が決め、決めきれない物だけが下書きになる。鎖は下書きを答えに替えない
4. 進みが無い: k 周目の差分が空（`result_k` の木＝`base_k` の木）→ `no_change`。k 周目の残りの行の鍵の集合が k−1 周目と同じ → `same_items`（行の鍵は `carry.row_key`。4.5）
5. 費用: 利用者が上限を決めた時だけ。累計 ＋ これまでの周の最大の費用 ＞ 上限 → `budget`（次の周で上限を越えうるなら起こさない）。どれかの周の費用が読めない → `cost_unknown`（上限を守れると言えないので止める。上限が無ければ読めなくても止めない）
6. どれにも当たらない → `go`

鎖の止めの語は、run の中の止めの理由（`state.stop.by`・考え `stop-reasons`）とは別の物で、鎖の控えと鎖の報告にだけ出る。

### 4.4 周の間に運ぶ物

次の周の依頼 `<鎖>/round-<k+1>-request.json` は、依頼のファイルの今の形（`{findings, pr, issue, answers, prior_failures}`）だけで書く。新しい欄は足さない。

- 差分: 基の版として運ぶ（`result_k`）。差分の根は `base_k`（3.2 の B2）
- 残りの所見: k 周目の `findings` のうち、下書きの印の無い行（今の `next_request` の行。直す穴）
- 前の失敗: k 周目の `prior_failures`（直す穴でない注意。判定役と修正案の役にだけ貼る今の道）
- 答え（4.5）: 1 周目の依頼の `answers`（利用者が名指した決め）と、1〜k 周目に人が関所で決めた問いの答え（`carry.human_answers`）。同じ `question` は新しい方を採る。下書きは運ばない
- 名指し: 1 周目の依頼の `pr`・`issue`（判定と目的の役が読む添え物）
- 運ばない物: 下書きの印の在る行。鎖の報告の「人が見る物」に並べる

### 4.5 答えを自分の項目に結ぶ（利用者の声の直し）

問いの key は判定役が run ごとに作るので、字の一致だけでは、依頼に書いた答えも前の周から運んだ答えも当たらない。結ぶのを判定役の仕事にし、機械が確かめる。

- 判定役の指示書の頭に、依頼の答えを全部並べる節を貼る（今は貼らない。`blk-judge/lib/judgebrief.py`）
- 判定役の返答に works の足し欄 `answer_ties` を足す（足し欄の住処 `.shared/core/marks.py` の `KINDS` に種 `answers` を 1 行。節は `p2.diagnose`）。行の形 `{"answer": "<答えの question の字>", "to": "<台帳の問いの key か単位の key>"}` か `{"answer": "…", "none": "<当たらない訳。20 字以上>"}`
- 受け付け（`blk-judge/scripts/accept.py`）は、依頼の答えの全部に 1 行が在ることと、`to` が今の返答の問いの key か単位の key に在ることを照らし、欠けと当たらない名指しを拒む（黙って落とさない）
- `gatemarks._hits` は字の一致の後に `answer_ties` の `to` を見る。結んだ答えは今の `answered` の道で問いを答えたことにし、`unmatched_answer_lines` に出なくなる。`none` の行はその訳つきで今の行に出る

### 4.6 鎖の報告

`<鎖>/chain.md` と、終わりに殻が出す行。頭の 3 行（何が起きたか・止めた訳・人が見る物）の後に:

| 周 | run | 結末 | 分 | $ | 残り | ファイル |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1a2b3c4d | round_limit | 21 | 7.70 | 5 | 3 |
| 2 | 5e6f7a8b | fixed | 24 | 8.10 | 0 | 2 |

- 合計の分と費用・止めた訳の 1 行・最後の差分のパスと当てるコマンド・人が見る物（運ばなかった下書きの行）・周ごとの報告のパス
- 残りの件数の並びは、全体の計画の段 6 の 6.3（止め時を所見の減り方で見る）の材料になる
- 費用と時間は、周ごとの run の報告と同じ所から読む（費用は `report.cost_rows` の和、時間は Archon の run の行の started_at と completed_at。`dev/canary_check.py:179` と同じ読み方）。新しい勘定を持たない（観点「履歴から作れる値は保存しない」。鎖の控えには周ごとの数を写すが、正本は Archon の記録）

### 4.7 最後の差分と取り込み

- `<鎖>/final.diff` は 元の基 → 最後に採った周の結果 の差（`git diff --binary`）
- 採る周: 最後の周から戻り、`report.stopped_run` が止まりと言わない最初の周（今の `use.sh apply` と同じ決まり）。止まった周の差分は、その周の `run-<id>.diff` として鎖の報告に名指す（捨てない）
- `use.sh apply <対象> <鎖の id>`: 今の apply と同じ確かめ（消す行の許し・`git apply --check`）で `final.diff` を当てる。run の id を渡した時は今どおり
- `use.sh show <対象> <鎖の id>`: `chain.md` を出す
- 対象の手元には、`apply` を打つまで何も当てない（今と同じ）

### 4.8 住処

- 持ち越し（考え `carry-over`）→ `.shared/core/carry.py`（Task 1）。依頼の容器の形・下書きの印・前の失敗の置き場・次の依頼の組み立て・行の鍵。層 L1（works のほかの物を import しない。`ghreads.py` が import する）
- 鎖（新しい考え `chain`）→ `.shared/core/chain.py`。鎖の控えの形・止めの語と決め・次の依頼の書き出し・鎖の報告の行。殻からは `python3 chain.py <口>`
- 結末の種 → 結末の住処 `report.py` に `OUTCOME_KIND` を足す（結末の語を鎖が文字列で持たない。考え `outcome` の柵）
- 起動の入力の組み立て → `dev/lib.sh` の 1 つの関数（今は `use.sh:777-796` に 1 か所。鎖で 2 か所目になるので部品へ寄せる）
- 包みの commit を作る所 → `dev/lib.sh` の 1 つの関数（今は `use.sh` の start の包み。4.2 の 3 で 2 か所目）

## 5. 鎖の控えの形

`<鎖>/chain.json`:

```json
{"id": "c-20261009-120000-4242", "target": "/abs/repo", "original_base": "<40 桁>",
 "rounds_max": 3, "budget_usd": null, "launch": {"test_cmd": "…", "tdd_suite": "…", "env": {"WORKS_USE_THICKNESS": "…"}},
 "first_request": "<1 周目の依頼の写しのパスか空>",
 "rounds": [{"n": 1, "run_id": "…", "base": "<40 桁>", "result": "<40 桁か空>", "outcome": "round_limit",
             "minutes": 21.0, "cost_usd": 7.7, "cost_known": true, "open_keys": ["…"], "held": 0, "files": 3,
             "request_file": "…", "report_file": "…", "diff_file": "…"}],
 "stop": {"word": "rounds_reached", "text": "…"}}
```

`held` は運ばなかった下書きの行の数（4.3 の 3 が読む）、`files` は周の差分のファイルの数（0 なら 4.3 の 4 の `no_change`）。`stop` は止めるまで `null`。書き込みは一時のファイルから `os.replace`。

## 6. 決め事（自分で決めた。訳つき）

1. 外の鎖にする（3.1）。線 B の枝は棚上げのまま残し、取り込まない
2. 次の周の差分の根は前の周の基（3.2 の B2。review-graph と同じ能力）
3. 既定は 1 周、`--rounds` は利用者が名指した時だけ。works の上限は置かない（持ち主「根拠の無い上限を置かない」）
4. 費用の上限は利用者が決めた時だけ。越えうる周を起こさない形で守る（越えてから止めると、利用者の決めた額を破る）
5. 人の判断が要る物で鎖を止める。下書きを答えに替えない（今の「機械は関所に答えない」）。4 つの軸で決めてよい物は run の中で決まる（全体の計画の段 2）ので、鎖に別の決め方を持たない
6. 答えの結び（4.5）は判定役に結ばせ、受け付けが欠けを拒む。字の一致の道は残す（今の依頼を壊さない）
7. 対象の手元へは `apply` まで当てない（今の取り込みの前の審査の機会を減らさない）
8. 鎖の報告は殻の外の Python が書く（AI の報告の役を起こさない。費用を足さない）。周ごとの AI の報告は今どおり

## 7. 持ち主に聞く（2 件）

### 決め 1: fixed で周が残る時、直しを確かめる周を 1 回足すか

- 足す（推し）: k 周目が fixed でも、周が残っていれば、k 周目の直しを差分にし依頼の行を空にした周を 1 回回す。P1 の役と判定が直しを見て、何も無ければ no_fix_needed で止まる。review-graph が「直した後の周に何も出ない」まで回すのと同じ能力
- 足さない: fixed で止める。今の 1 周の run と同じ終わり方。安い
- 推す訳: 持ち主の判断の基準（review-graph との能力比）と観点 `independent-verdict`。費用は 1 周分（約 $8）増えうるが、利用者が N と上限で抑えられる
- 決めずに進めない訳: 能力と費用がぶつかり、どちらの観点も持ち主の言葉に在る（`close-in-round`「1 周目のうちに直しきる」・`run-cost`）

### 決め 2: いつ入れるか

- 段 4 の後（推し）: 全体の計画の段 4（入口ブロック）の後に「段 4b」として入れ、段 5 の持ち越しをこの計画の Task 1・2 として前に出す
- 段 1 の後すぐ: 利用者が困っているので早い。代わりに、段 4 の入口の作り替えと `entry.py` で重なり、どちらかが当て直しになる
- 推す訳: 鎖は段 4 が無くても動く（2 周目からの入力は今の「両方」と「変更だけ」の形で、今の穴は差分が空の時だけ。B2 の次の周は差分を持つ）。それでも Task 1 が `entry.py` の `place_prior` を動かすので、段 4 の後の方が当て直しが無い
- 決めずに進めない訳: 段の順は持ち主が決めた道のりの並べ替え

## 8. 既存の計画への変更

全体の計画（`2026-10-09-clean-whole.md`）。状態の行に、この文書を指す 1 行を足すだけにし、本文は次に書き直す人が直す:

- 6 節「やらないと決めた」の「周を重ねる線（線 B）」: 持ち主 2026-10-09 の決めで「頼まれたら周をつなぐ」に替わった。作りは線 B でなく外の鎖（この文書）。線 B の行は「線 B は棚上げのまま。周は外の鎖で」に直す
- 段 5 の 3（carry-over）: この文書の Task 1・2 に移す。足す物: 答えの結び（4.5）と人が決めた答えの持ち越し。段 5 の順は「止めの理由 → 関所 → 帳簿 → …」になる
- 段 6 の 6.3（止め時の見積もり）: 「持ち越しの鎖の上で見る」の鎖はこの文書の鎖。鎖の報告の残りの件数の並び（4.6）を材料にする
- 5 節の段の図: 段 4 の後に段 4b（この文書）を足す（7 節の決め 2 で替わりうる）
- 8 節の棚卸し: `carry-over` を住処あり、新しい考え `chain` を住処ありで足す

入口の計画（`2026-10-09-one-entry-shape.md`）: 変えない。鎖の 2 周目からの run は入力の形の普通の入口（`base` と依頼の行）で、入口の種を足さない。段 4 が入った後は、鎖が渡す入力 `base` が入力の形の `base.from = "base"` になるだけ。

README の「足りない所」と「仕様」の線 B の行、`skills/works/SKILL.md` の起動の節: Task 8 で書き直す。

## 9. 全体の縛り（どの Task にも効く）

- 線の YAML・写しの核（`.shared/core/graphloops/`）・台帳 `COPIED_FROM` は変えない
- ブロックは鎖を知らない。run の中のどこも「何周目の鎖か」を読まない（入力に鎖の欄を足さない。鎖の印は起動の印 `launch_mark` の字の中だけで、読むのは殻）
- 依頼のファイルの形（`{findings, pr, issue, answers, prior_failures}`）を変えない。新しい欄は works の足し欄（`marks.py`）だけ
- 結末の語は `report.py` の外に文字列で書かない（柵 `outcome`）
- `carry.py` は標準ライブラリだけ・Python 3.9 で動く形（`ghreads.py` が `python3 -I` で読む）
- 試験は日本語の docstring・unittest・今の helper（`tests/gitkit.py`・`tests/test_use.py` の偽の archon）。HEAVY の試験は手元で回さず CI（push して `gh run`）
- 手元の確かめ: `python3 works/tests/tiers.py fast` とリポジトリの根の `sh ~/.cache/works-dogfood/rootfences.sh`
- 版上げは最後の commit で、`VERSION_BUMP_STRICT=1` を手元でも

## 10. 見張る所（使う人が踏みやすい物。各行の試験は持ち主の Task に足してある）

1. 2 周目の起動が落ちた（認証切れ・Archon が起きない）: 鎖の控えは「k 周目まで済み・次は起きていない」を残し、`use.sh show <鎖>` が続きの打ち方（`use.sh chain-resume <対象> <鎖>`）を出す → Task 5 の `test_launch_failure_leaves_resumable_chain`
2. 周の差分が対象の手元の変更とぶつかる: 鎖は対象の手元を触らないので起きない。`apply` の時だけ今の `git apply --check` が止める → Task 6 の `test_chain_apply_checks_like_run_apply`
3. 差分が対象のファイルを消す: `final.diff` にも今の消す行の許し（`WORKS_USE_ALLOW_DELETE=1`）が効く → Task 6 の `test_chain_apply_refuses_delete_without_allow`
4. 同じ対象で鎖を 2 本並べる: 鎖の id と参照の名が別なので混ざらない。`start` の古い run の片付け（`sweep_old_runs`）が、走っている鎖の前の周の run を消しても、結果は参照で守られていて困らない → Task 5 の `test_two_chains_do_not_share_refs`
5. 1 周目の依頼が `-`（`--base` か `--pr` だけ）: 2 周目からの依頼は前の周の残りだけで組む。1 周目の答えは無い → Task 3 の `test_next_request_without_first_request`

## 11. Task（TDD の順）

並べ方: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9。2 と 4 は 1 の後に並べてよい（触るファイルが分かれる）。

### Task 1: 持ち越しの住処 `carry.py`（振る舞いは変えない）

**Files:** Create `works/.shared/core/carry.py`・`works/tests/test_carry_home.py`。Modify `works/.shared/core/ghreads.py`（容器の形の定数と `request_parts`・`_answers`・`_prior_failures`・`carry_ci` を移し、PR・issue の読みだけ残す）・`works/.shared/core/report.py`（`NEXT_REQUEST_FILE`・`next_doc` の組み立てを carry から引く）・`works/.shared/core/entry.py`（`PRIOR_IN_FILE`・`place_prior`・`prior_section` を移す）・呼び手（`blk-judge/lib/judgebrief.py`・`blk-plan/lib/planblk.py`・`blk-judge/scripts/intake.py`・`blk-premises/scripts/intake.py`・`dev/lib.sh` の `next-request.json` の名・殻の `carry-ci` の口）・`works/docs/concepts.md`・`works/docs/concepts.json`（`carry-over` を住処ありにし柵を足す）・`works/tests/test_layers.py`・`works/tests/tiers.py`。今の試験の import 先（`tests/test_carry_ci.py`・`tests/test_report.py`・`tests/test_gate_drafts.py`・`tests/test_out_of_purpose.py`・`tests/test_entry.py`）

**Interfaces:**
- Produces（名と形は今のまま移す）: `carry.NEXT_REQUEST_FILE`・`KEYS`・`ANSWER_KEYS`・`DRAFT_KEYS`・`PRIOR_KEYS`・`CI_WHERE`・`PRIOR_IN_FILE`・`parts(doc) -> dict`（今の `request_parts`）・`carry_ci(doc, ids) -> dict`・`place_prior(board_dir, rows) -> None`・`prior_section(board_dir) -> str`
- Produces（新）: `carry.compose(findings: list, prior: list, drafts: list) -> dict`（今の `next_doc` の中身。盤面を知らない）・`carry.is_draft(row) -> bool`・`carry.row_key(row: dict) -> str`（`where` と、`text` の最初の「（」までを空白を詰めて `\t` でつないだ物。Task 3 が使う）

- [ ] 赤: `test_carry_names_live_in_carry`（柵の表の行 `carry-over` が通る＝`next-request.json`・`prior-failures-in.json`・`DRAFT_KEYS` の字が住処と知ってよい所の外に無い）・`test_compose_then_parts_roundtrip`（`compose` の返りから下書きの行を外すと `parts` が通る）・`test_row_key_ignores_reason_tail`（`{"where": "a.py", "text": "k1（修正がやらなかった: 理由 A）"}` と理由だけ違う行が同じ鍵）・`test_ghreads_keeps_only_github_reads`（`ghreads` に `KEYS` が無い）
- [ ] 回して赤を見る: `python3 works/tests/tiers.py fast -k test_carry_home`
- [ ] 移す。呼び手を carry に向け、古い名を残さない（`grep -rn "ghreads.request_parts\|ghreads.DRAFT_KEYS\|entry.place_prior\|entry.PRIOR_IN_FILE" works/` が 0 件）
- [ ] 速い段と根の柵が緑。commit `refactor(works): 次の run への持ち越しの形を core の carry に 1 つにまとめる（書き手・読み手・置き場が同じ名を引く）`

### Task 2: 答えを自分の項目に結び、人が決めた答えを持ち越す

**Files:** Modify `works/.shared/core/marks.py`（`KINDS` に `answers`）・`works/.shared/core/gatemarks.py`（`_hits` が足し欄を見る・`answer_ties` の形と確かめ）・`works/blk-judge/lib/judgebrief.py`（答えの節）・`works/blk-judge/scripts/accept.py`（欠けを拒む）・`works/blk-judge/commands/diagnose.md`（欄の書き方）・Create `works/blk-judge/schemas/answer-ties.schema.json`・Modify `works/blk-judge/manifest.json`・`works/.shared/core/carry.py`（`human_answers`）・`works/.shared/core/report.py`（`next_doc` が人の答えを `answers` に足す）。Test `works/tests/test_plan_gate.py`・`works/tests/test_blk_judge.py`・`works/tests/test_gate_drafts.py`・`works/tests/test_report.py`

**Interfaces:**
- Produces: 判定役の返答の足し欄 `answer_ties: [{"answer": str, "to": str} | {"answer": str, "none": str}]`（4.5）
- Produces: `gatemarks.ties(b) -> dict[str, str]`（答えの question → 結んだ問いの key。`none` の行は入れない）
- Produces: `carry.human_answers(gate_rows: list, request_answers: list) -> list`（人が関所で continue した問いと依頼の答えを `{question, text}` の行に。`text` の頭に「run <id> の関所で人が決めた: 」。下書きの印を持たない）

- [ ] 赤: `test_answer_tied_by_judge_hits_question`（答え `question: "自分の項目 a.py"` を判定役が key `q-7` に結ぶ → `answered(b, q7)` が真・`unmatched_answer_lines` が空）・`test_judge_must_account_every_answer`（答え 2 件・足し欄 1 件 → 受け付けが拒み、文に欠けた question）・`test_tie_to_unknown_key_refused`・`test_none_tie_reported_with_reason`・`test_literal_key_still_hits`（今の字の一致の道）・`test_next_doc_carries_human_answers`（関所で continue した問いが次の依頼の `answers` に下書きの印なしで載り、`carry.parts` が通る）・`test_drafts_still_refused`（下書きの行は今どおり拒む）
- [ ] 回して赤を見る（`test_blk_judge` のうち HEAVY の物は CI）
- [ ] 入れる
- [ ] 緑。commit `feat(works): 依頼の答えを判定役が問いか項目に結び、受け付けが結び忘れを拒む。人が決めた答えを次の依頼へ運ぶ`

### Task 3: 鎖の決め `chain.py`（純粋な関数）

**Files:** Create `works/.shared/core/chain.py`・`works/tests/test_chain.py`。Modify `works/.shared/core/report.py`（`OUTCOME_KIND`）・`works/docs/concepts.md`・`works/docs/concepts.json`（考え `chain` を住処ありで足す）・`works/tests/tiers.py`

**Interfaces:**
- Consumes: Task 1 の `carry.parts`・`carry.is_draft`・`carry.row_key`、Task 2 の `carry.human_answers`
- Produces: `report.OUTCOME_KIND: dict[str, str]`（語 → `closed`・`open`・`halted`・`waiting`・`broken`。4.3 の 2）
- Produces: `chain.STOPS: dict[str, str]`（止めの語 → 1 行の文。語は `rounds_reached`・`closed`・`halted`・`needs_human`・`no_change`・`same_items`・`budget`・`cost_unknown`）
- Produces: `chain.verdict(doc: dict, *, confirm: bool) -> dict`（`{"go": "go"|"wait"|"stop", "word": str, "text": str, "next_empty": bool}`。`confirm` は 7 節の決め 1。`next_empty` は確かめの周＝依頼の行を空にする周）
- Produces: `chain.next_request(round_doc: dict, first: dict | None, carried: list) -> tuple[dict, list]`（次の依頼と、運ばなかった下書きの行）
- Produces: `chain.round_row(...) -> dict`・`chain.load(path) -> dict`・`chain.save(path, doc) -> None`（5 節の形。`os.replace`）

- [ ] 赤: `test_every_outcome_has_kind`・`test_stop_order`（4.3 の 1〜6 を 1 本ずつ。N に達した周が fixed でも語は `rounds_reached`）・`test_fixed_with_rounds_left_confirms`（`confirm=True` → `go`・`next_empty`、`False` → `closed`）・`test_drafts_stop_for_human`・`test_empty_diff_is_no_change`・`test_same_keys_twice_stop`・`test_budget_predicts_next_round`（上限 $20・累計 $15・最大の周 $8 → `budget`）・`test_unknown_cost_stops_only_with_budget`・`test_interrupted_waits`・`test_next_request_drops_drafts_and_keeps_first_answers`・`test_next_request_without_first_request`（10 節の 5）・`test_chain_has_no_outcome_strings`（柵 `outcome`）
- [ ] 回して赤を見る: `python3 works/tests/tiers.py fast -k test_chain`
- [ ] 入れる
- [ ] 緑。commit `feat(works): 周の鎖の決め（止める条件・次の依頼・控えの形）を core の chain に置く`

### Task 4: 殻の部品を寄せる（起動の入力の組み立てと包みの commit）

**Files:** Modify `works/dev/lib.sh`（`works_dev_launch_args`・`works_dev_tree_commit`）・`works/dev/use.sh`（start の 777-796 行と包みの所を部品の呼び出しに）。Test `works/tests/test_use.py`

**Interfaces:**
- Produces: `works_dev_launch_args <家> <依頼> <test_cmd> <tdd_suite> <from> [<base>] [<launch_mark>]`（`workflow run darkfactory …` の引数を `set --` に組む。`WORKS_USE_*` を読む所はここだけ）
- Produces: `works_dev_tree_commit <対象> <親の版> <diff か空> <参照の名> <message>`（一時の index で親の木に diff を当てて commit し参照で守る。diff が空なら作業ツリーを包む今の道）

- [ ] 赤: `test_start_args_unchanged_after_refactor`（今の start が偽の archon に渡す引数と同じ）・`test_tree_commit_applies_diff_on_parent`（gitkit の種で、親に diff を当てた commit の木が、diff を当てた作業ツリーの木と同じ・未追跡の追加も入る）
- [ ] 入れる（振る舞いは変えない）
- [ ] 緑。commit `refactor(works): use.sh の起動の入力と包みの commit を dev/lib.sh の部品にする（周の鎖で 2 か所目になるため）`

### Task 5: `--rounds` と周のつなぎ

**Files:** Modify `works/dev/use.sh`（旗 `--rounds`・`--budget-usd`・拒む組・start と wait の終わりで鎖を 1 歩・口 `chain-resume`）・`works/dev/lib.sh`（`works_dev_chain_step`）・`works/.shared/core/chain.py`（殻の口 `main`: `verdict`・`record`・`next`）。Test `works/tests/test_use.py`

**Interfaces:**
- Consumes: Task 3 の `chain.verdict`・`next_request`・`round_row`、Task 4 の 2 つの部品
- Produces: `use.sh start --rounds N [--budget-usd X]`・`use.sh chain-resume <対象> <鎖>`・鎖の控え（5 節）

- [ ] 赤（偽の archon。`workflow run` の引数を控えに残す今の形を使う）: `test_rounds_flag_parsed_before_positionals`・`test_rounds_refuses_bad_values`（`0`・`1.5`・`x`）・`test_rounds_refuses_design_only_and_fixture`・`test_no_rounds_makes_no_chain`・`test_chain_launches_next_from_result_with_prev_base`（2 周目の起動が `--from <result_1> --input base=<base_1> --input launch_mark=<鎖>-2`）・`test_chain_stops_on_closed`・`test_wait_continues_chain_after_answer`（1 周目が paused → `answer` → `wait` が終わりを見て 2 周目を起こす）・`test_launch_failure_leaves_resumable_chain`・`test_two_chains_do_not_share_refs`・`test_round_line_shows_cost_and_cap`
- [ ] 入れる
- [ ] 緑。commit `feat(works): use.sh start --rounds N で、前の周の結果を基にし残りを依頼にして次の run をつなぐ`

### Task 6: 最後の差分と取り込み

**Files:** Modify `works/.shared/core/chain.py`（`final_round(doc) -> int`）・`works/dev/use.sh`（`apply`・`show` が鎖の id を受ける）。Test `works/tests/test_use.py`・`works/tests/test_chain.py`

- [ ] 赤: `test_final_diff_spans_original_base_to_last_kept_round`・`test_halted_last_round_excluded_and_named`（`report.stopped_run` が止まりと言う周は採らず、その diff を報告に名指す）・`test_chain_apply_checks_like_run_apply`・`test_chain_apply_refuses_delete_without_allow`・`test_show_chain_prints_report`
- [ ] 入れる・緑・commit `feat(works): 周の鎖の差分を元の基からの 1 本にまとめ、use.sh apply・show が鎖の id を受ける`

### Task 7: 鎖の報告

**Files:** Modify `works/.shared/core/chain.py`（`report_lines(doc) -> list[str]`）・`works/dev/lib.sh`（止めた時に `chain.md` を書いて出す）。Test `works/tests/test_chain.py`

- [ ] 赤: `test_report_head_three_lines`（止めた訳と人が見る物）・`test_report_rows_per_round_and_totals`（4.6 の表の値と合計）・`test_report_names_held_drafts`・`test_report_cost_unknown_is_named`（読めない費用を 0 と書かない）
- [ ] 入れる・緑・commit `feat(works): 周の鎖の報告（周ごとの結末・時間・費用と合計・止めた訳・最後の差分）を書く`

### Task 8: 文書と版

**Files:** Modify `works/README.md`（「足りない所」と「仕様」の線 B の行・打ち方）・`works/skills/works/SKILL.md`（起動の節に `--rounds`）・`works/docs/darkfactory-flow.md`（全体の図の外に鎖の 1 段落）・`works/docs/owner-decisions.md`（観点 `carry`・`stop-by-rate` の住処と隙間）・`works/docs/plans/2026-10-09-clean-whole.md`（8 節の変更を本文へ）・`works/CHANGELOG.md`・版の控え

- [ ] 文書を書き直し、速い段と根の柵が緑
- [ ] 最後の commit で版を上げる（`VERSION_BUMP_STRICT=1`）。push して `gh run` で CI（HEAVY を含む）が緑か見る

### Task 9: 本物の鎖で確かめる（コードの変更なし）

- [ ] canary の種で 1 周目に残りが出る依頼（`canary.sh --request large`）を `--rounds 3` で回す（約 1 時間・約 $25 の見込み）。見る物: 2 周目の起動の引数・2 周目の P1 の役が 1 周目の直しを見た・鎖の報告の表と合計が周ごとの報告の費用と合う・`use.sh apply <鎖>` が当たる
- [ ] 無人（`WORKS_USE_UNATTENDED=1`）で同じ鎖: 関所で止まった周で `needs_human` で止まり、下書きが鎖の報告に並ぶ
- [ ] 周ごとの P0 の費用（修正前の CI・前提・目的・並行 PR）を数え、12 節の 3 を決める材料としてこの文書の末尾に残す

## 12. 危うさ

1. **周を重ねても同じ所で止まる**（壊れる余地）: 今の利用者の run でも、同じ 2 つの穴で止まる run が在った。`same_items` が 2 周目の終わりで止めるので、無駄は最大 1 周
2. **費用が見えないまま膨らむ**（壊れる余地）: 周の境ごとに累計を 1 行出し、上限を決めた人には越えうる周を起こさない。上限を決めない人には N が上限
3. **周ごとに P0 を回し直す重さ**（壊れる余地）: 2 周目の修正前の CI は、1 周目の最後のテストと同じ木を測り直すことが多い。Task 9 の数で、同じ木の結果を使い回すか（全体の計画の段 7 の「修正前の木でテストのコマンドを 2 度走らせる件」と同じ扱い）を決める
4. **判定役が答えを無理に結ぶ**（壊れる余地）: 結び先は今の返答の問いか単位に在ることを機械が確かめるが、意味の合う結びかは確かめない。結んだ答えは今どおり報告と最後の関所に「依頼者の答え」で並ぶので、人が見て気づける
5. **周の差分の作り直しが worktree と食い違う**（壊れる余地）: 周の結果は `run-<id>.diff` を基に当てて作るので、`show` の差分の作り方（未追跡を含む・消す行）と同じ物になる。`show` が差分を書けなかった周（終了コード 4）は結果を作らず、鎖は `halted` と同じに止めて理由を出す（Task 5 の試験に足す）

## 13. 考えの棚卸し（この計画自身）

| 考え | 今の住処 | 計画の後 | 知る場所 |
| --- | --- | --- | --- |
| carry-over | 散らばり | `carry.py` | 減る |
| chain（新） | 無い | `chain.py` | +1 |
| outcome | `report.py` | `report.py` | 0 |
| marks | `marks.py` | `marks.py` | 0 |
| 起動の入力 | `use.sh` | `dev/lib.sh` | 0 |
| 包みの commit | `use.sh` | `dev/lib.sh` | 0 |
