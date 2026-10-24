# 変更の記録（rent-or-buy）

rent-or-buy（「借りるか買うか」を計算だけで決める Claude Code のプラグイン。keepalive と compact の判断に当てる。keepalive はキャッシュが切れないよう送る短い要求、compact は会話を要約して縮める操作）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]（まだ版を付けていない変更。版を出すときに版の見出しへ移す）

### Added

- 最初の版（これから出す 0.1.0 の中身）。借りるか買うかを決める計算の部品 `bin/rent-or-buy`（`decide`・`keepalive`・`compact`・`prices`・`snapshot`）。標準入力の JSON を受け、標準出力の JSON を返し、判断の状態を持たない。`decide` は中心をそのまま呼び、`keepalive`・`compact` は場面の事実を中心の入力に直して（翻訳）判断し、`prices <モデル>` は使う単価と出どころを返し、`snapshot` は同梱の値段の写しを作り直す。設計は `docs/specs/2026-10-24-rent-or-buy-design.md`。
  - 中は 2 つのモジュール。`rent_or_buy/` は Claude を知らないアルゴリズム（決め方の表と最初の `fixed`・強制と延期の上限・問い合わせ口・判断の記録）、`prompt_cache/` は Claude のプロンプトキャッシュへの当てはめ（LiteLLM（モデルの値段表を公開している外部のプロジェクト）の値段表の写しと、1 日 1 回までの取り直し（取れなければ写しで計算する）・モデル名の揃え・会話の記録の読み取り・翻訳）。境目の 4 つの決まり（アルゴリズムは標準ライブラリと自分だけを読む・キャッシュの層はアルゴリズムの表の口だけを使う・プラグインの外から 2 つのモジュールを読み込まない・アルゴリズムに Claude の語を書かない）を `tests/test_boundary.py` が守る。
  - `fixed` は、借り賃が一定なら後から見た最適の費用の 2 倍未満で借りるのをやめて買う（借り賃が回ごとに変わるときの保証は指南 3.5 に従い、この試験は一定の場合だけ）。
