# 変更の記録（works-factory）

works-factory の Claude Code 側の入口（`/works-factory` スキルと殻 `bin/works-factory`）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

## [0.1.8] - 2026-10-16

### Changed

- `works-factory/PIN` を raiki61/works-factory の 2e5e55c7 に上げた。run の深さを軽量・標準・重厚の 3 段にし、計画の事前審査を深さで飛ばす道を外した（重厚は判定の裏取りと木の事前審査を足す）・無人の run（`unattended=true`）は承認ノードで推しを採って進み、計画の壁打ちが安全の上限に届いた時は止める・計画の足す物と消す物をファイル構成の行にし、行ごとに考えの住処と退けた置き場を持たせる・修正の組の子の run が落ちたら run を止め、resume で続きから回す・受け付けに拒まれた出し直しを同じ役の会話の続きで直させる・字のぶつかりの印をファイルの中身と重ならない長さで書いて照らす、などが入る。
- スキルの深さの説明を 3 段に合わせ、無人の run の起こし方を書いた。

## [0.1.7] - 2026-10-15

### Changed

- 変更の記録の冒頭の、版の出し方の案内を直した（git の tag は作らない）。利用者に効く違いは無い。

## [0.1.6] - 2026-10-15

### Changed

- `works-factory/PIN` を raiki61/works-factory の 9365c286 に上げた。軽い依頼では run の頭で深さを決めて計画の事前審査を飛ばす（代わりに独立の目を必ず回す）・承認済みの受け入れ条件のテストが変わったら承認し直すかを人に問う・今の works から落ちていた能力の総点検と戻し・試験が走ったかを証拠が在る時だけ言う直しの残り・公開ベンチの台（プロキシの要る網・remote の無い課題・submodule の在る課題）が入る。
- スキルに、`findings` を省ける依頼と仕様の段の止め、報告の入口の深さの 1 行を書いた。

## [0.1.5] - 2026-10-14

### Changed

- `works-factory/PIN` を raiki61/works-factory の bfc23c48 に上げた。run の作業ツリーを対象の今の姿（commit していない変更を含む）から切る・一部の CI の系統が回せない時も回せた系統で進む・手元を指す `test_cmd` を起こす前に止める・「試験が走らなかった」を証拠が在る時だけ言う、が入る。
- スキルの起動の説明を、上の作業ツリーの起点と `test_cmd` の確かめに合わせた。

## [0.1.4] - 2026-10-14

### Changed

- `works-factory/PIN` を raiki61/works-factory の 53213e16 に上げた。試験が走らなかった時に報告の冒頭で名指す・試験のコマンドの環境を利用者が明示した時だけ家の設定に戻す・全部の AI ノードの出し直し・認証の案内・公開ベンチの台の直しが入る。
- スキルに、試験が家の設定を要る時の 2 つの道（手元で回す・`WORKS_FACTORY_TARGET_USER_ENV=1` を付ける）と、付けると資格に届くことを書いた。

## [0.1.3] - 2026-10-14

### Fixed

- スキルの起動の説明を実物に合わせた: 依頼は JSON のファイルのパスで渡す（文は受けない）。作業ツリーは `--from` を付けないと既定の枝から切られる。`test_cmd` を省いた時の動き。

## [0.1.2] - 2026-10-14

### Changed

- スキルに、keychain の項目の名を Claude Code の `settings.json` の `env` に `WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` に当たる組を書いて渡す道と、「認証が無い」で止まった時に項目の名を推して試さず人に聞くことを書いた。

## [0.1.1] - 2026-10-14

### Changed

- 止めた commit（`works-factory/PIN`）を raiki61/works-factory の eefaa6c2 に上げる。周の鎖（`works-factory-chain`。頼まれた周の数まで回し、最後の差分と周ごとの表 chain.md を出す）・組の合わせ（並べた組を合わせて赤になったら合わせ役が直し、直せなければ裁定へ）・記録された方針だけを方針として扱う直し・審査する変更とこの run の直しの出どころを分ける直しが入る。

## [0.1.0] - 2026-10-14

### Added

- `/works-factory` スキル: 今いるリポジトリを対象に、修正依頼を works-factory（raiki61/works-factory）へ回す入口。今の `/works` には触らず、並べて置く（持ち主の決め `coexist-before-switch`）。
- 殻 `bin/works-factory`: 止めた commit（`works-factory/PIN`。raiki61/works-factory の 909588a9）を `${XDG_CACHE_HOME:-~/.cache}/works-factory-plugin/<commit>` に取り置き、その殻に引数をそのまま渡す。`apply` は差分を当てる口 `bin/apply` に渡す。
