# works と darkfactory の設計（2026-09-26）

状態: 持ち主と会話で合意した設計の書き起こし。実装計画はこの文書を元に別に書く。

## 平易版（3 行）

- 持ち主の普段の作業を、Archon（AI の工程を YAML で書いて機械が順に回す外の道具）の上に移していく。その入れ物が `works`、最初の生産ラインが `darkfactory`（人の修正依頼を、判定 → 修正 → テスト → 人の承認 → 修正の審査の順に流す）。
- 工程の並べ方は Archon に任せ、差を付けるのは「AI の返答を何で受け付けるか」——graphloops（このリポジトリの既存のプラグイン）の規則と記録の検証器を写してきて、中身が通ったときだけ次へ進める。
- ブロック（節のまとまり）を Archon の工程 1 つとして 1 フォルダずつ持ち、ラインはブロックを `include:` で並べるだけにする。並び替え・差し替え・付け足しはラインの数行を替える作業で、噛み合わない並びは Archon の読み込みの検査（お金を使う前）で落ちる。

## 0. 狙い（持ち主の言葉から）

- この形に載せ換えておけば、次に別の土台へ移るときも、自分で engine を作るときも、載せ換えが楽になる。**ノウハウ（何を判定させ、何で受け付け、どう並べるか）を資産として綺麗に保存する**のが狙いである。
- 保存の書式は **Archon の規約に寄せる**（持ち主の判断 2026-09-26）。Archon の工程の書式は特定の用途に縛られない汎用の物で、約束の仕組み（入力の宣言・返す節・返答の型・成否の欄）も持っている。自前の書式を別に立てても、移る先でまた訳すことになるので得が薄い。
- 自前で持つのは、Archon の規約が「コードに置け」と言っている物だけ——受け付けの規則と記録の検証器（script の節から呼ぶ Python）である。

## 1. 持ち主の決定（2026-09-26）

- リポジトリ直下に独立したディレクトリ `works/` を切り、Archon の pack（`archon plugin install` で入る工程の束）の根にする。大枠は汎用の名前 `works`、中のライン 1 本目が `darkfactory`。調べる工程（research）などは後から足す。
- **元のプラグイン（graphloops・convergence-loops）には触らない**。要素は写して持ってきて、写しは独立に育てる。元と同じかを確かめる柵は置かず、写した元の commit だけを記録する。
- 工程の正本は Archon の YAML に手で書く。graphloops の graph の JSON から YAML を作る変換器は作らない。
- Archon を包む層は作らない。Archon は公式の配布物（release の実行ファイル）で入れる。
- works 自前の薄いスキルを 1 本付ける（Archon の一般的な操作は Archon 本体の `archon-cli` スキルに任せる）。
- 作り方は coleam00/ai-software-factory（以下 ASF）の良い部分を取ってよい。丸ごとは真似ない。ASF には LICENSE ファイルが無いので、取るのは考え方だけでコードは写さない。
- 開発は superpowers の流れ（仕様 → 実装計画 → TDD → 審査）。graphloops の `/review-graph` に通す決まりは works には当てない。
- 引き継ぎから続く方針: 期限・タイムアウトを新しく足さない（Archon が有限の値を必須にする所だけ 20 日 = 1,728,000,000 ms）／今ある能力を減らす必要が出たら持ち主に聞く／push と tag と Archon の開発元への issue・PR は持ち主の指示を待つ／変異テストの本撃ちはしない。

## 2. 位置づけ

- **Archon に差す**。ASF は固定した Archon の源を抱えて自前の CLI（`consumer.py`）で包む形、works は `archon plugin install raiki61/claude-plugins/works@<tag>` で差し込まれる pack の 1 つで、利用者は `archon workflow run raiki61/works:darkfactory` を直に打つ。
- 外側の組み方（1 工程 1 フォルダ、`include:` と `with:` で部品を並べる）は Archon 同梱の工程集 sdlc と同じになる。これは Archon の標準の組み方で、ここで差は付けない。
- 差を付けるのは次の 2 つ。
  1. **受け付けの厳しさ**: sdlc は返答の形（`output_format`）が合えば受け付ける。works は形の上で graphloops の規則と検証器が中身を通したときだけ受け付け、拒めば同じ会話で出し直させる。
  2. **ブロックの切り方**: graphloops で積んだ知見（どこで区切れば修正を TDD 版や外の実装に差し替えられるか、どこに人の関所を置くか）でブロックを切る。約束そのものは Archon の仕組みで持つ（3 節）。

## 3. 層（Archon の作法「YAML coordinates. Code computes. Agents judge.」に沿う）

出典: Archon 本体 `.archon/workflow-language-constitution.md`（commit 879c99fe）。

1. **ライン（YAML）** —— 節の順番・受け付けの輪・人の関所・上限だけ。`when:` には欄の比べだけを書き、計算を書かない。
2. **役（`commands/*.md` と `output_format`）** —— 判定役・修正役・審査役への指示書と返答の型。判断はここだけ。
3. **つなぎ（ブロックの `scripts/*.py`）** —— Archon の口（`$節.output`・`$ARTIFACTS_DIR`・`$INPUTS`）を読み、中身の関数を呼び、決まった JSON を 1 行で返す。拒否も終了コード 0 で `ok: false` を返し、読めないときだけ 2 で落ちる。
4. **中身（`.shared/core/`）** —— 規則の関数・記録の検証器・型。Archon を知らない。Archon 無しで単体テストが回る。

約束は Archon の仕組みで持つ（自前の約束のファイルは置かない）:
- ブロックの入口は `inputs:`、出口は `returns:` が指す節の `output_format`、成否は `outcome_field`。
- 読み込みの時に Archon が確かめる（879c99fe の源で確かめた）: `with:` の鍵と `inputs:` の突き合わせ・宣言の外の鍵の拒否、前の節の出力の欄を読むときにその欄が相手の `output_format` に在るか（`packages/workflows/src/output-ref.ts`）、`outcome_field` が返す節の `output_format` に在るか（`loader.ts`）。
- 同梱の工程集 sdlc の作法も使う: 成果物の報告は `archon_artifact` の指し（在るファイルでなければ節を拒む）、構造のある値はスクリプトへ `with: {欄: {from: "$節.output.欄"}}` で型のまま渡す、修正の前の版は `$節.execution.checkoutStart` で取る。

## 4. 構成## 4. 構成

```
works/
├── archon-plugin.json          name: works／entrypoints: {darkfactory: darkfactory/darkfactory.yaml}／compatibility.archon
├── README.md
├── docs/specs/                 この文書
├── .shared/
│   └── core/                   中身（graphloops から写す。8 節）
│       ├── COPIED_FROM         写した元の commit と写した物の一覧
│       └── ...
├── darkfactory/                ライン（入口）
│   ├── darkfactory.yaml
│   └── fixtures/*.stubs.yaml   ライン全体の筋書き
├── blk-judge/                  ブロック（support workflow。ラインからしか使えない）
│   ├── blk-judge.yaml          入口（inputs）・出口（returns の節の output_format）もここに書く
│   ├── commands/diagnose.md
│   ├── scripts/accept.py
│   └── fixtures/*.stubs.yaml
├── blk-fix/
├── blk-tests/
├── blk-delta/
├── tests/                      中身とつなぎの単体テスト・返答の見本（直下に YAML を置かない）
├── dev/                        固定した版の Archon を隔離した HOME で回す殻・使い捨ての対象リポジトリを作る道具
└── skills/works/SKILL.md       works の薄いスキル（配り方は 12 節）
```

- Archon の決まり（879c99fe で確かめた）: pack の根の直下のフォルダのうち、直下に YAML がちょうど 1 本あるものが工程になる。ドット始まりのフォルダ・直下に YAML が無いフォルダ（`tests/`・`dev/`・`docs/`・`skills/`）は工程として読まれない。install は symlink・submodule・`\`・`:` を含むパスを拒む。
- 名前: ラインは素の名前（`darkfactory`・後の `research`）、ブロックは `blk-` を頭に付ける。

## 5. ブロックと組み替え

### 5.1 1 ブロックの持ち物

- `<blk>.yaml`: Archon の工程 1 つ。`inputs:` に入口の欄、`returns:` に出口を集める節、その節の `output_format` に出口の型、`outcome_field` に成否の欄。
- `commands/*.md`: 役の指示書。Archon の変数（`$INPUTS.<名>`・`$節.output` など）をそのまま使う。
- `scripts/*.py`: つなぎ（受け付け・確かめ）。
- `fixtures/*.stubs.yaml`: このブロック単体の筋書き。
- 受け渡し: 小さい値は `$節.output.欄`、大きい物（単位の表など）は `archon_artifact` の指しか `$ARTIFACTS_DIR` の下のファイルのパス。

### 5.2 ラインでの並べ方

```yaml
name: darkfactory
interactive: true            # 人の関所を持つので必須（背景では回せない）
inputs:
  request: {required: true, description: 人の修正依頼（findings の JSON の配列）のファイルのパス}
  test_cmd: {required: true, description: テストのコマンド}
nodes:
  - id: judge
    include: blk-judge
    with: {request: $INPUTS.request}
  - id: fix
    include: blk-fix
    depends_on: [judge]
    with: {judgment: $judge.output.judgment_file}
  - id: tests
    include: blk-tests
    depends_on: [fix]
    with: {cmd: $INPUTS.test_cmd}
  - id: gate
    approval: {message: "テストは $tests.output.result。修正差分の審査へ進めてよいか", capture_response: true}
    depends_on: [tests]
  - id: delta
    include: blk-delta
    depends_on: [gate]
```

（欄の名前は形の例。確定は実装計画で。）

### 5.3 組み替えの 4 通り

1. 並び替え: ラインの `depends_on` を書き換える。
2. 差し替え: 同じ入口（`inputs:`）と出口（返す節の `output_format`）を持つ別のブロックへ `include:` の名前を替える（例: `blk-fix` → TDD で直す `blk-fix-tdd`）。噛み合わなければ Archon の読み込みの検査で落ちる。
3. 付け足し: 雛形からブロックのフォルダを作り、筋書きと出口の型を先に書いて赤を確かめ、中身を書き、ラインに `include:` を 1 つ足す。
4. 新しいライン: 別の入口の YAML が同じブロックを並べ直す。

### 5.4 組み替えを守る検査

- 並びが噛み合うかは Archon の読み込みの検査（`archon validate workflows`）に任せる（3 節）。自前の突き合わせは作らない。
- 自前で足すのは 1 つだけ: 役の節の `output_format`（YAML に書いた返答の型）と、受け付けの規則が前提にする返答の形がずれていないか。良い返答の見本が「YAML の `output_format`」と「受け付けの規則」の両方を通ることを単体テストで確かめる（型の検査には写した中身の `engine/schema.py` を使う。標準ライブラリだけで動く）。

## 6. darkfactory の 1 本目（範囲）

試作（本体のセッションが 2026-09-26 に回した spike。`S/archon-spike/REPORT.md`）の一切れを製品にする。

| ブロック | 中の節 | 関所 | 輪 |
|---|---|---|---|
| blk-judge | 判定役 → 受け付け → 集める | なし | 受け付けの出し直し（上限 3） |
| blk-fix | 修正役 → 受け付け → 変えたかの確かめ → 集める | なし | 受け付けの出し直し（上限 3） |
| blk-tests | テストのコマンド | なし | なし |
| （ラインの節） | 人の承認 | あり | なし |
| blk-delta | 差分を切る → 審査役 → 受け付け → 集める | なし | 受け付けの出し直し（上限 3） |

- 受け付けの出し直し: `loop_group`（`until_bash: test $accept.output.ok = true`・`fresh_context: false`・`max_iterations: 3`）。2 回目以降の役は同じ会話の続きで起き、拒んだ理由を `$LOOP_PREV.accept.output.reason` でプロンプトに貼る（試作で実走、REPORT.md 3 節 (c)）。上限を超えれば run は失敗で止まり、`archon workflow resume` で続きから回せる。
- loop_group の出力は型を持てないので、輪の後ろに集める節を置く（本体のセッションのブロックの設計書 `S/blocks/BLOCKS.md` の 1 節の事実。S = 本体のセッションの scratchpad `/private/tmp/claude-1341252503/-Users-p03623-src-claude-plugins/799d1c5c-a888-4cdb-bf0a-ac1aea9c5577/scratchpad`）。
- 判定役に渡す依頼は、graphloops の `add` と同じ findings の型（欄は `where`・`text` 必須、`mechanism`・`measured`・`false_positive_if` 任意）。起動の前に、依頼の欠け（問題・重要性・急ぎ度・成果・壊してはいけない条件・受け入れの基準）を確かめる検査を入口に置く（Archon の `archon-cli` スキルの起動前の確かめを取り入れる）。
- 指示書は graphloops の `prompts/review-loop/` の p2.diagnose・p3.fix・p3.delta_review を元に、Archon の変数で書き直す。graphloops の指示書は engine の盤面の穴（`{{record.materials}}` など）を前提にしているので、1 本目で盤面に無い物（P1 の素材・前の周の記録・台帳）は削り、受け付けの規則が要求する欄（反証・class_query・precedents・one_shot_closes・questions）を書かせる部分は残す。
- 範囲の外（次の段以降）: 修正案と事前審査（BLOCKS.md の R5）・修正の手直しと 2 回目の審査（R7 の 2 回目）・周の輪（2 周目以降）・前提（R1）・素材集め（R3）・独立の目（R11）・周の締め（R12）・報告（R13）・変異の検算（R9）・research のライン。

## 7. 守り

- **読むだけの役**（判定役・審査役）: `allowed_tools: [Read, Grep, Glob]`、`sandbox.enabled: true`。Archon の AI の節は全部 `bypassPermissions` で起きる（試作で確かめた）ので、書く道具を持たせないことが主な守り。`mutates_checkout: false` は include で入ると落とされる（Archon の文書: run が持つ設定）ため当てにしない。代わりに受け付けの前に作業ツリーが変わっていないかをつなぎで確かめる。
- **書く役**（修正役）: Archon が run ごとに切る worktree の中で動かし、`sandbox.enabled: true` で Bash の書き込みを worktree の中に限る。残る穴: Edit・Write の道具は bypass の下で OS の柵が掛からない。今の graphloops でも修正は回す側の会話がしていてこの柵は無いので、能力は減らない。引き継ぎ文書は「書く役は script の節から graphloops の `role_run.py` で起こす」としていたが、1 本目は Archon の AI の節のまま置く（同じ会話での出し直し・`output_format` の型・節ごとの費用の記録を Archon に任せられるため）。任せ先を OS の柵の中で起こす守り（graphloops の delegate）が要る節は 1 本目に無い。
- **何もせず済んだと言うのを止める**: 修正役の後に「差分が空でないか」を確かめる決まった検査の節を置く（sdlc の `assert-changed` の考え方）。
- **期限**: AI の節の `idle_timeout` と bash・script の節の `timeout` は 20 日。2^31−1 ms（約 24.8 日）を超える値は Archon の検査を通るのに実行で即失敗するので、`tests/` で YAML の期限が上限の内かを確かめる。
- **止め方**: 前景の run を SIGTERM で止め、`archon workflow resume` で続ける（Archon の素の機能。試作で確かめた）。人の関所を持つラインは背景（`--detach`）で回せず、外から cancel もできない。止め札のファイル（ASF の `halt`）は次の段で考える。
- **Archon への直し**: 試作の A〜D は使わない。素の版で回る形にする。

## 8. 中身（`.shared/core/`）の写し

- 写す元: このリポジトリの commit fbd40e3（graphloops 0.20.3）。
- 写す物（1 本目で要る物）: `graphloops/engine/`（rules の読み込みと、rules が import する util・schema）・`graphloops/rules/review-loop.py`・`graphloops/graphs/review-loop.json`（rules の読み込みと役の返答の型の元）・`scripts/review-record.py`・`scripts/record_common.py`。どれも標準ライブラリだけで書かれている（確かめた）。
- `COPIED_FROM` に commit と写した物の一覧を書く。写した後は works の物として直す。
- つなぎから中身を呼ぶ口は、最初は試作の `gl_accept.py` の形（rules が読む盤面の口だけを持つ入れ物を渡す）で始め、試作が残した欠け（BLOCKS.md 5.4 節）のうち 1 本目で効く物を直す:
  - 周の頭で固めた版を run の入力として持ち、その場の `git rev-parse HEAD` を使わない。
  - 中身の置き場をスクリプトの位置から決め、絶対パスを埋めない。
  - 返りの形をブロックの出口の型に揃える。
- その後、規則の関数を BLOCKS.md 5 節の形（読み口を受けて `{ok, reason, reply, effects, note}` を返す純粋な関数）に 1 本ずつ直す。直した関数から、呼ぶブロックの近くへ移してよい。

## 9. 確かめた事実（Archon 879c99fe）

- 実行の時、pack は run ごとに丸ごと写され、写しの中から動く（`.git` と `__pycache__` だけ除く）。script の節は写しの中の絶対パスで起き、`Path(__file__).resolve().parents[2]` が pack の根の写しになる。
- include で入ったブロックの `script: <名>` は、そのブロック自身の `scripts/` から解決される。`.shared/core` を import できる。`with:` の値は bash の節の `$INPUTS.<名>` と環境変数 `INPUTS_<名>` の両方に届く。（2026-09-26、使い捨ての対象リポジトリの project pack で実走して確かめた。AI の節なし）
- include は読み込みの時に節を平らに展開し、節の名前は `<includeの名>__<節>` になる。`$<includeの名>.output` はブロックの `returns:` の節（無ければ最初の末端）を指す。
- `archon plugin install` は GitHub の tag か既定の枝の先頭からしか入らず、手元のパスからは入らない。開発中は対象リポジトリの `.archon/workflows/works/` に置く project pack で回す（この形では manifest は無視され、工程は YAML の `name:` で起きる）。
- run の題名を付けるために Archon が別に Claude を 1 回呼ぶ。認証が無いとその呼び出しだけが失敗し、run は続く。

## 10. テスト（TDD で先に赤を書く）

1. **中身とつなぎの単体テスト**（`tests/`、Python の unittest）: 良い返答と悪い返答の見本を、写した規則と検証器に通して通る・拒むを見る。悪い見本を拒むことが「検査の検査」になる（ASF の自己検査の考え方）。Archon 不要、数秒。
2. **返答の型のずれ・期限の上限**（5.4・7 節）: YAML とファイルを読むだけ。Archon 不要。
3. **読み込みの検査**: 使い捨ての対象リポジトリに pack を置き、固定した版の Archon で `archon validate workflows`。
4. **筋書き**: Archon の `fixtures/*.stubs.yaml`（AI の返答を差し替えた筋書き）で `--dry-run`。ブロックごとと、ライン全体。お金を使わない。拒否 → 出し直し → 通過の筋書きを含める。
5. **実走**: 試作と同じくバグを仕込んだ使い捨てのリポジトリで回す（1 回約 0.5 ドル）。節目にだけ手で撃つ。

- 1〜3 は `works/tests/run.sh` 1 本で回す。このリポジトリの CI（`.github/workflows/test.yml`）へのつなぎ込みは共有のファイルを触るので、持ち主に聞いてから。
- テストは `nice -n 19` で前景で回す。プロセスを止めるときは pid と cwd を確かめてから止める（`pkill -f` の広い形を使わない）。

## 11. 配布と版

- `archon-plugin.json` の `compatibility.archon` で、動くと確かめた版の範囲を宣言する（最初は `>=0.11.1 <0.12.0`）。Archon を上げるときは 10 節の 2〜4 を通してから範囲を広げる。
- 開発の殻（`dev/`）は、固定した版の Archon の実行ファイル（GitHub の release の `archon-darwin-arm64` など）を落として sha256 を確かめ、HOME・`ARCHON_HOME`・Claude の設定を隔離して回す。認証は macOS の keychain の `claude-code-oauth-p1` から起こすたびに読み、ファイルに書かない。利用者に配る物ではない。
- tag（例 `works-v0.1.0`）と push は持ち主の指示を待つ。それまでは project pack で回す。

## 12. works のスキル

- `works/skills/works/SKILL.md` に、依頼の JSON の書き方・どのラインに回すか・人の関所で何を見て答えるかだけを書く。起動・待つ・承認・再開は `archon-cli` スキルに任せる。
- Claude Code のプラグインとして配るには `works/.claude-plugin/plugin.json` と、リポジトリ直下の `.claude-plugin/marketplace.json` への 1 行が要る。marketplace.json は共有のファイルなので、足すのはスキルを書き終えた段で持ち主に確かめてから。

## 13. 未決・危うい所

- 修正役を Archon の AI の節のまま置く判断（7 節）は、引き継ぎ文書の案（script の節から role_run で起こす）と違う。実走で書く道具の漏れが問題になれば、role_run の形へ移す。
- Archon は版上げでよく互換を壊す（0.8〜0.11 の全部に互換を壊す変更の節がある）。範囲の宣言と筋書きのテストで受け止める。
- 本体のセッションは graphloops 側で自前の約束の書式（`graphloops/blocks/<ブロック>/block.json` と入口・出口の型）と `gl` コマンドを作る計画で進んでいる（`S/blocks/BLOCKS.md`）。works は約束を Archon の規約で持つので、書式が分かれる。ブロックの切り方（どの節を 1 つにまとめるか）と規則の関数の形（読み口を受けて JSON を返す）は BLOCKS.md に倣う。
