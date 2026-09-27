# 変更の記録（graphloops）

graphloops の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版を名指しする git の tag（例: `graphloops--v0.21.1`）の名前の決まり・付け方・付ける commit の一覧への案内と、この記録を書き足す段は、リポジトリのルートの `docs/releasing.md` に在る（プラグインとして入れた実体には無いので、clone か GitHub で見る: https://github.com/raiki61/claude-plugins/blob/main/docs/releasing.md）。0.19.0 以前の版はこの記録に無い。git の履歴の「版を上げる」の commit を見る。

## [Unreleased]

### Added

- `loop.py skip --every-round`: optional の節を run の間ずっと、出す前に省く（回し切りの口）。
- `loop.py relaunch --if-untouched`: 前の試行の子を止め切り、作業ツリーと HEAD・枝が起こした時点と同じときだけ書き換える子を起こし直す。engine は落ちた書き換える子をこの確かめを通して 1 回だけ自動で起こし直す。
- 書き換える節の申告（graph の `declared_files`）: 返答が名乗ったファイルと、作業ツリーで実際に変わったファイルを両方向で突き合わせ、食い違いを記録に残す。次の周の判定者が読む。

### Changed

- 書く子が申告の外に書いても受け付けを拒まず、記録と所見に残す（回し役の居ない run を止めない）。
- git の状態の柵は、自分の作業ツリーの HEAD と枝だけを比べる。全作業ツリーで共有する stash と作業ツリーの一覧は、並行の run が動かしても受け付けて trace に残す。P1 の前後の突合の基準から stash の一覧を外した。
- 作業ツリーの前後の突合は、状態とパスの並びに加えて中身の木の id も比べる。読むだけの節・skill の節は作業ツリーへ書く手に数えない。
- engine が起こす書く子に、子ごとの一時の置き場を渡す。sandbox の中で書けない版なら共有の置き場へ戻す。
- 書く子の指示書に、人の方針・宣言した検査の回し方・申告の決まりを届ける。
- 義務の行（`rows`）を持たない旧い版の出力は、止めずに差分レビューの出力から数え直し、測れなかった痕跡を残す。
- （開発）pytest の層 2 の筋書き（上限で止まる類と、止める・人待ちの筋書き）を足した。bash の台本はまだ残る。

### Fixed

- Windows で、申告のファイル名が作業ツリーと違うドライブを指すと受け付けが落ちていた。
- UTF-8 でないファイル名の綴りが、Windows でだけ盤面に別の綴りで残っていた。

## [0.21.5] - 2026-09-27

### Added

- 宣言した検査の一式（`.review-checks.json` の `suite`）が全段緑で終わったら、同じ指紋（作業ツリーの中身・段の定義・実行の土台）の間は別の run でも走らせずに使い回す。必ず走らせるなら `launch` の環境に `GRAPHLOOPS_RERUN_CHECKS=1`。
- 子を止める猶予を環境変数 `GL_KILL_GRACE=<秒>` で選べる。
- ブロックの約束の置き場 `blocks/`。graph は節の出口の型を `$ref` で指し、graphcheck が所属・出口・並列の上書き・共有の核を照らす。
- 外から規則を呼ぶ口 `scripts/gl.py`。
- 盤面を横断して run の質を engine の版ごとに数える、読み取り専用の台本 `scripts/quality-ledger.py`。
- 変更の記録（この文書）と、版を出す手順（リポジトリの `docs/releasing.md`）。

### Changed

- 規則の関数を読み口と effects の形へ移し始めた。run の状態（盤面の `loop`）は graph の `state_schema` の合わせ方（`x-reducer`）と effect の口だけで書き、`loop.py patch` で `loop` を変えた手当ては合わせ方を飛ばした痕跡を残す。
- 同じ周の擦り合わせを 3 往復まで回す（回ごとに回す側が再異議を書く節を置いた）。3 回とも決着しなければ第三の目が立つ。
- 手順書に回す側の手の心得（人の居ない手番で消す操作を打たない・背景はハーネスの背景実行で・結果は盤面で見る）を足した。

## [0.21.4] - 2026-09-27

### Added

- engine が走らせる CI の節（`p0.local_checks`・`p4.ci`）を人の命令で省く口。
- `init --engine-runners`: 回す側の節を engine が `claude -p` で起こす（書き換える節は OS の sandbox の中で作業ツリーだけに書ける）。

### Changed

- `loop.py patch` が親を新設したときにそう言う。盤面・trace に書く値の引数の読めないバイトは入口で拒む。
- comment-analyzer を読むだけに狭めて engine が起こす。

## [0.21.3] - 2026-09-27

### Added

- `loop.py children`: 盤面の印から子の残りを一覧し、止める。
- 審査の役に貼る差分が `launch.input_budget_bytes` を超えた周は、節を要約した写しを貼り、全文は Read 1 本で読ませる。

### Changed

- ブロックの出口の値を盤面の `loop` から節の出力へ移した（`hist.snapshot`・`hist.after_fix` で読む）。旧い盤面の鍵は警告して次の周の頭で外す。
- 消す口の柵を graphloops・tests・scripts の全部に広げた。

## [0.21.2] - 2026-09-27

### Added

- `loop.py run`: 回し手が engine の起こせる節を回し続け、会話に返す節・人の答え待ち・周の止め・終わりでだけ終了コードで戻る。1 つの run に回し手は 1 本で、盤面の置き場の錠で決まる。`init --stop-after-round` で止めた run は `loop.py resume` で次の周へ進める。
- `loop.py patch` で節の最新の出力の欄を書ける（`out.<節>.<欄>`。節の返答の型で照らす）。`--delete` もこの形に通る。
- 周をまたぐ値を記録の履歴から作る、読み取り専用の口（`hist.`）。patch でこの値は書けない。
- 設計の決定の記録（ADR）をリポジトリの `docs/adr/` に置き、先行議論を洗う役（`p0.prior_decisions`）がそこを読む。

### Changed

- 盤面の保存を置き場の錠の下で「読み直し→比べる→書く」にした。回し手・会話・人が同時に書いても割り込まれない。
- 盤面の `loop` を片付けた。`flow`・`gates` などの値は `loop` に写さず、`inputs` と節の出力から読む。
- 背景の任せ先の線を止める手順を手順書に書いた。止めた線は同じ周に起こし直さない。

## [0.21.1] - 2026-09-27

### Added

- `answer --detail`: 修正の前の人の関所で、直す義務の単位をその周の修正から外せる。外した単位と理由は記録に残る。
- `loop.py patch --delete` と、`--path` の `record.` 接頭（付けても付けなくても同じ所を指す）。
- `loop.py launch` が落ち方を `cause` の 3 値（`launch_auth`・`launch_child_failed`・`launch_auth_unread`）で返す。
- 盤面の `loop` の形を graph の `state_schema` に宣言し、graphcheck が読みを照らし、engine が保存の時に照らす。
- 修正の入口を単位の番号にした（`p2.fix_units`）。役は一覧を番号で指し、engine が名前に戻す。
- graph の `extends` を何段でも重ねられる。
- 検査の宣言に engine の知らない段が在っても、知っている段は走らせ、P0 で人に確かめる。engine の知らせ（notices）が報告に載る。

### Changed

- 変異の関門を Google 型にした（変わった行だけ・1 行 1 本・行を通した台本だけで撃つ）。
- CI の見送りに能力の名前を持たせ、OS ごとの「欠けてよい能力」の一覧で数える。
- 修正役が当たった先行例を、次の周の判定役へ渡す。問いの key の重複を拒む。

### Fixed

- 子を止める口が、グループの外へ出た孫と、ゾンビだけのグループを取り違えない。正常に終わった試行の残りの子も止める。
- 人が関所で単位を外した周に、外した単位を直さない修正が拒まれていた。
- windows-latest の CI の赤（0.21.0 の 12 件と pytest の 13 件）を直し、3 OS で緑に戻した。

## [0.21.0] - 2026-09-26

### Added

- `init --stop-after-round N`: N 周目の締めまで済ませて止まる。
- `init --input gates=merge`: 変異の検算を run の中で撃たず、合流した版でまとめて撃つ。
- engine が走らせる節: CI の再実行（`p0.local_checks`・`p4.ci`）は、対象リポジトリのルートの宣言 `.review-checks.json` のコマンドを engine が走らせ、終了コードから結果を組む。
- `loop.py stop`: 人が途中で止める口。止めた理由が記録に残り、報告の節だけが走る。
- 人の方針: run をまたいで効く人の決まりを 1 つの文書に置き、各節に届ける。今ある能力を減らす変更と方針とぶつかる変更は、修正の前後の関所（`p2.human_gate`・`r4.human_gate`）で人に聞く。
- 踏んだ問題を利用者の環境に 1 件 1 行で残す記録器と `/graphloops:intake`。
- Bash を持つ役を OS の sandbox の中で起こす。外へ問い合わせを出せる役に検索語の規律を持たせた。

### Changed

- 宣言のコマンドを走らせる前の人の承認を外し、走らせる直前に宣言と突き合わせる。
- 検証器だけが持っていた判定の規則を、役の返答の受け付けでも当てる。graphcheck が節の知らない鍵を照らす。
- `/security-review` のレンズを、条件の関数で当てる。

### Fixed

- テストの台本が `launch` の失敗時に `/` を消しにいく欠陥を塞いだ。

## [0.20.3] - 2026-09-26

### Fixed

- windows-latest の CI の赤 6 件を直し、3 OS で緑に戻した。直したのはテストの台本・代役・変異の道具だけで、製品のコードは変えていない。

## [0.20.2] - 2026-09-26

### Added

- `init --unfenced-delegates <理由>`: 人が run ごとに明示したときだけ、任せ先の sandbox を外す。外した事実は盤面に残る。

### Changed

- 重い工程のコマンドの説明を「起動は人が打ったときか『工程に回して』と言ったときだけ・AI は提案まで」に揃えた。`/review-graph` の説明が、人の修正依頼を判定から入れる入口を指す。

### Fixed

- 任せ先を engine が OS の sandbox の中で起こす。作業ディレクトリは本物の写しで、本物の作業ツリーと `.git` には書けない。0.20.1 では、Agent ツールで起こした任せ先が本物の作業ツリーで `git checkout` と `git reset --hard` を打ち、回す側の未コミットの修正を消した。
- CI を 3 OS で緑に戻した（git の名前とメールの無い環境・Windows の文字コードと symlink）。

## [0.20.1] - 2026-09-25

### Fixed

- 役の標準出力が `claude -p` の JSON の包みでなくても、全文を本文として受け付けに回す。途中で engine だけ上げた run で、役の所見が捨てられていた。
- research-graph: ゲートの前に止まった run でも報告が出る。
- research-graph: 未解決の開いた問いが残っていれば、収束の文言を「閉じた主張の検証は収束した」と「開いた問い K 件は未解決」に分ける。案内の中の存在しないコマンド名を `add` に直した。

## [0.20.0] - 2026-09-25

### Added

- 判定から入る入口: `loop.py add` で人の修正依頼を置くと、素材集め（P1）を外して判定から始まる。
- 役を engine が `claude -p` の子プロセスとして起こし、子の終了を直接待つ（`loop.py launch`）。拒まれた返答は同じ会話に出し直させる。
- 変異の検算を並行の線に出し、周の締めは待たない。収束の前に、最終の版で撃ち直す関門を置く。
- pytest の土台（`graphloops/tests/py/`）。
