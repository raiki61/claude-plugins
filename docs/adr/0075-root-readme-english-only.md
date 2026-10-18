# 0075. 根の README は英語の 1 版だけにし、日本語の訳の版を持たない

- 状態: 採用
- 日付: 2026-10-18
- 決めた人: 回す側の推し（説明書の担当。持ち主の頼み「外部の人に使ってもらうことを考えると英語がいい。煩わしくなければやっておいていい」と、持ち主の 2026-10-18 の決め「英語の正本は claude-plugins の repo の README と docs の 1 つだけにする」による。受付 da159a）
- 実装: 作業枝で済み（根の `README.md`）

## 文脈

- claude-plugins は公開して外の人に配っているが、根の README は日本語で、英語の読み手は入れ方から分からなかった。
- 持ち主の条件は「煩わしくなければ」。2 つの言語を手でそろえ続ける手間を、持ち主にもエージェントにも増やさない。
- 世間の形: GitHub は README を `.github`・根・`docs` の順に探して 1 つを出し、言語の版の仕組みは持たない。言語の版を持つ OSS は、英語の `README.md` の横に言語の接尾辞の付いた版（`README.zh-CN.md` など。lobehub/lobe-chat）を置き、頭に互いを指す行を置く。訳を元の文と揃える文書の仕組み（OpenTelemetry）は、英語を元とし、訳した頁ごとに元の頁のコミットを書き、古くなった訳を道具（`check:i18n`）で一覧にする。英語を直すと訳は古くなったまま残り、言語のチームが直す。

## 決定

- 根の `README.md` を英語だけで書く。日本語の訳の版（`README.ja.md`）は持たない。
- 英語の README の「Language」の節に、ほかの文書（各プラグインの README・スキルとコマンド・CONTRIBUTING.md・`docs/`）は日本語だと書く。
- `docs/` は英語にしない。中身は設計の決定・会社の形・改善の台帳など、持ち主とエージェントが日本語で保守する記録で、使い始める人が読む物ではない。

## 比べた案

- 英語の `README.md` と日本語の `README.ja.md` の 2 版を持ち、訳の頭に元の版を書いて、ずれを試験で落とす（捨てた案）: 世間の形に合い、ずれは機械で見つかるが、根の README の直しのたびに 2 版を直す手間が残る（2026-09-18〜10-18 の 30 日で根の README の直しは 17 回）。日本語の読み手（持ち主とエージェント）は、根の README の中身（プラグインの一覧と入れ方）を各プラグインの README と `.claude-plugin/marketplace.json` から日本語で読める。
- 各プラグインの README と `docs/` まで英語だけにする（段取りの小さい案を広げた物。捨てた案）: `docs/` は約 100 本・7,500 行の日本語の記録で、持ち主とエージェントの保守の言語を変えてしまう。各プラグインの README はその担当の受け持ちで、`tests/run.sh` が日本語の語を照らす検査を持つ。決めるなら担当ごとに別に決める。
- 今のまま日本語にする（捨てた案）: 外の人が入れ方から読めない。

## 理由

- 1 版だけなら、そろえる相手が無いので、ずれが起きない。
- 持ち主の決め（英語の正本は repo の README と docs の 1 つ）に字のまま合う。

## 結果

- 楽になる: 英語の読み手が根の README から入れられる。訳をそろえる手間が無い。
- 難しくなる: 根の README を直すエージェントは英語で書く。プラグインの README を開いた英語の読み手は日本語に当たる。
- `tests/run.sh` の README_PLUGINS_OK（表と本数が marketplace.json と揃うか）は、本数の文の英語の形（`ships N plugins`）も認める（点検の担当に頼んだ。受付 b7df98）。

## 見直す条件

- 各プラグインの README を英語にするかを、担当か持ち主が決めたとき。2 言語の版を持つなら、上の捨てた案の形（英語を元とし、訳の頭に元の版を書き、ずれを試験で落とす）にする。

## 出どころ

- [GitHub Docs の About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)・[OpenTelemetry の Site localization](https://opentelemetry.io/docs/contributing/localization/)・[lobehub/lobe-chat](https://github.com/lobehub/lobe-chat)（2026-10-18 に読んだ）。
