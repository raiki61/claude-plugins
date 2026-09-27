# 変更の記録（works）

works（Archon の上の生産ライン darkfactory の pack と、Claude Code 側の入口 `/works` スキル）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版を名指しする git の tag（例: `works--v0.2.0`）の名前の決まり・付け方と、この記録を書き足す段は、リポジトリのルートの `docs/releasing.md` に在る。0.1.0 はこの記録に無い。

## [Unreleased]

### Changed

- 入れ方を、Claude Code のプラグインを 4 つ入れる（works・superpowers・coldwrite・pr-review-toolkit）だけにした。リポジトリの clone も、その場所を置く環境変数も要らない。`/works` スキルの行は、入れたプラグインの置き場の `dev/use.sh`・`stop.sh`・`report.sh` を起こす。
- AI の役が借りる superpowers のスキル・coldwrite・pr-review-toolkit を、利用者が Claude Code に入れた版から取るようにした（本線の graphloops と同じ。版は Claude Code が今に保つ）。確かめるのは works が名前で使うスキル・agent・hook が在ることだけ。入っていない物があれば、`use.sh check`・`start` は AI を起こす前に、足りない物ごとの 1 行と入れるコマンドを出して止まる。使った版と置き場は今までどおり `.works-toolset.json` と run ごとの `versions.json` に残る。

### Removed

- works の中に置いていた superpowers（6.4.2）のスキルと pr-review-toolkit の写しと、その使用許諾の表示のファイル（NOTICE）を消した。works は第三者の物を同梱しない。

### Fixed

- Claude Code のプラグインのキャッシュに入った works から `use.sh` を起こすと、coldwrite の元（works の外の marketplace.json）が無くて `check` も `start` も止まっていたのを直した。
- pack の出どころの控え（`.works-source.json`）が、works が git で追跡されていない時に別のリポジトリの commit を works の版として書くことがあったのを直した。その時は commit を null にし、プラグインの版を書く。

## [0.2.0] - 2026-09-28

### Added

- darkfactory の線を、判定の前後と修正の後ろまで広げた。前提の実測・目的の文・素材集め → 判定 → 修正案と事前審査 → 修正 → 差分の審査 → 手直し → 最後のテスト → 人の最後の関所 → 独立の目 → AI が書く報告と初見検査、の順に流れる。自分食いの run（dd68321e）で、図の最初から最後まで通り、結末 fixed になった。
- 修正の段に、単位ごとの TDD の輪を足した。テストを書く → 機械が赤を確かめる → 直す → 機械が緑を確かめる → 整える、を単位ごとに回す。テストの実行器が無い対象は、今までどおり直接直す。
- 修正役と TDD の役が「依頼・テスト・コードが食い違っている」と証拠つきで申し出る出口と、それを裁く読むだけの役を足した。裁けない物・能力を下げる物だけが最後の人の関所に上がる。
- 守りのファイル（works 自身の試験・柵・受け付けの口）の一覧を足した。run の差分がこれに触れると、最後の人の関所が必ず開き、冒頭にファイルと規則が並ぶ。
- 修正役の指示書を、共通の決まりと道ごとの決まりから機械で組む形にした。同じ会話の続きには、決まりの全文でなく差分だけを渡す（包みが起動の時に選ぶ）。
- 変えたファイルから影響するソースとテストを機械で引く地図（`.shared/core/impact.py`）と、変えたファイルが使うライブラリの今の文書を Context7 から取って修正の指示書に貼る口を足した（`WORKS_CONTEXT7=off` で止める。役が自分で Context7 を引く口は既定で切り、`WORKS_CONTEXT7_MCP=on` で入れる）。
- 他のリポジトリで使う起動の殻 `works/dev/use.sh`（`check`・`start`・`show`）と、`/works` スキルの入口の説明を足した。
- run ごとの版の一覧（`versions.json`）を、盤面の隣に書く。
- 見張りごとの軽い自己点検 `works/dev/selfcheck.py`（見張りの 1 行を壊して、見張る試験が赤になるかを確かめる）を足した。

### Changed

- AI の役は全部、選んだ物だけを置いた隔離した Claude Code の設定（借りた superpowers の 5 つのスキル・coldwrite・pr-review-toolkit）を読む。
- 役の道具を、本線（graphloops review-graph）の同じ役以上にした。判定・修正案・事前審査・修正・手直しの役が Web を引ける。
- 役の出し直しの輪は、3 回目の拒否で理由を書いて盤面を止め、報告まで届く（run ごと落とさない）。
- 最後の人の関所は、線の最後（最後のテストの後）に 1 つだけ置く。
- 自分食いの殻 `works/dev/dogfood.sh` は、既定で包みを通して役を起こす。

### Fixed

- Claude Code が役の作業フォルダに作る `.claude/.cc-writes/`（どの深さでも）を、読むだけの役の作業ツリーの見張りが変更と数えて拒んでいた。
- 修正役が判定に異議を書くと、再審の節が線に無いため最後のテストが走らなかった。
- 節が落ちると報告も出口も残らなかった。今は機械の報告と次の run の依頼の下書きを必ず残し、Archon の run の状態は失敗のままにする。
- 修正案の役が直す単位を番号で指すと、役の出口の型が文字列だけを許していたため毎回拒まれていた。
