# 変更の記録（rent-or-buy）

rent-or-buy（「借りるか買うか」を計算だけで決める Claude Code のプラグイン。keepalive と compact の判断に当てる）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

### Added

- 最初の版。借りるか買うかを決める計算の部品 `bin/rent-or-buy`（`decide`・`keepalive`・`compact`・`prices`・`snapshot`）。標準入力の JSON を受け、標準出力の JSON を返し、状態を持たない。設計は `docs/specs/2026-10-24-rent-or-buy-design.md`。
  - 中は 2 つのモジュール。`rent_or_buy/` は Claude を知らないアルゴリズム（決め方の表と最初の `fixed`・強制と延期の上限・問い合わせ口・判断の記録）、`prompt_cache/` は Claude のプロンプトキャッシュへの当てはめ（LiteLLM の値段表の写しと 1 日 1 回の最新・モデル名の揃え・会話の記録の読み取り・翻訳）。境目の 4 つの決まりを `tests/test_boundary.py` が守る。
  - `fixed` は、借り賃が一定なら後から見た最適の 2 倍未満で止まる。
