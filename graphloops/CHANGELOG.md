# 変更の記録（graphloops）

graphloops の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版を名指しする git の tag の名前は `graphloops--v<版>`（例: `graphloops--v0.21.1`）の形と決めてあり、その版を上げた commit に人が付ける。どの版に tag が在るかは、リポジトリの tag の一覧（GitHub の tags か `git ls-remote --tags origin`）で確かめる。tag の付け方と、この記録を書き足す段は、リポジトリのルートの `docs/releasing.md` に在る（プラグインとして入れた実体には無いので、clone か GitHub で見る: https://github.com/raiki61/claude-plugins/blob/main/docs/releasing.md）。0.19.0 以前の版はこの記録に無い。git の履歴の「版を上げる」の commit を見る。

## [Unreleased]

### Added

- `loop.py run`: 回し手が engine の起こせる節を回し続け、会話に返す節・人の答え待ち・周の止め・終わりでだけ終了コードで戻る。1 つの run に回し手は 1 本で、盤面の置き場の錠で決まる。`init --stop-after-round` で止めた run は `loop.py resume` で次の周へ進める。
- `loop.py patch` で節の最新の出力の欄を書ける（`out.<節>.<欄>`。節の返答の型で照らす）。`--delete` もこの形に通る。
- 周をまたぐ値を記録の履歴から作る、読み取り専用の口（`hist.`）。patch でこの値は書けない。
- 設計の決定の記録（ADR）をリポジトリの `docs/adr/` に置き、先行議論を洗う役（`p0.prior_decisions`）がそこを読む。
- 変更の記録（この文書）と、版を出す手順（リポジトリの `docs/releasing.md`）。

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
