# works で作業するエージェントへ

works/ の下で作業するときの決まり。Claude Code は works/ の下のファイルを読んだときにこのファイルを読み込む。ルートの CLAUDE.md の決まりも全部効く。works に関わる決まりのうち、works/ のファイルを読まない会話にも効かせたい物（graphloops などから写すときの決まり・darkfactory の run の打ち方）は、ルートの CLAUDE.md の「プラグインを作る・直す」に置いた（2026-11-04、頼み b6bca1）。

## works（Archon の pack）

works は、コードの直しの頼みを AI の段（調べる・計画する・直す・レビュー・試験など）の流れで回す Claude Code のプラグイン。Archon は YAML に書いた AI の段を順に回すツールで、pack は Archon に載せるワークフローのひとまとまり。流れの本体は darkfactory というワークフロー（中身は works/README.md）。

- works/ は独立した pack。graphloops・convergence-loops から要素を写すときの決まりは、ルートの CLAUDE.md の「プラグインを作る・直す」に在る（graphloops などのファイルを直す会話にも効かせるため）。
- works の直しは darkfactory に流すのが本来の形。危ない直しは run（darkfactory の 1 回の実行。`works/dev/use.sh start` で起動する）を通す。グラフ全体を変える直しは、工場が遅い間の暫定として会話の下請けで作り、本物の run で確かめる（持ち主 2026-10-07・2026-10-09「これは工場が遅いから今暫定的にやってるだけ。工場がよくなったら工場がいい」）。どの道の変更も同じ機械のゲート（考えの住処のチェックと数の歯止め）を CI で通す。考えの住処のチェックは、設計の考え 1 つを持つと決めた 1 か所（住処。一覧は works/docs/concepts.md）の外にその考えが漏れたら赤になる試験。数の歯止めは、住処のまだ無い考えについて、今その考えを知っている所の数が増える差分を赤にする試験。
- ブロック（blk-*）とノードは疎結合に。ノードは darkfactory の 1 つの段で、ブロックは関係するノードをまとめた部品（入口の `blk-entry` など）。線（works/darkfactory/darkfactory.yaml）は、どのブロックをどの順でつなぐかを書いた darkfactory の流れの定義。ブロックの中に他のブロックの名前・出口・振る舞いを書かず、在る前提でも書かない。入力は形（ポート）で述べ、どのブロックが作るかは線（works/darkfactory/darkfactory.yaml）の側に書く。
- 言語: 人と話す所だけその人の言語。言語の選び方の仕組み（自動検出など）は works で作らない（環境・ハーネスに任せる）。
- 作り替えのついでに今ある能力を取りこぼさない（keep-essence の 12 の仕組みは外さない）。期限・タイムアウトを新しく足さない。

## 出荷（works の版）

1. 手元の試験はルートの CLAUDE.md の「試験」のセクションと同じく速い段とルートのチェックまで（重い段は main に入った後の CI に任せる）。ルートのチェックは VERSION_BUMP_STRICT=1 を付けて回す（`VERSION_BUMP_STRICT=1 bash tests/run.sh`。版上げの順の検査は main・release/* の CI でだけ厳しくなるため）。
2. CHANGELOG の Unreleased を版に。
3. **版上げ（works の plugin.json・marketplace）を最後の commit にする。** 版上げの後に works を変える commit を積むと main の CI が赤になる（0.2.2 で実測）。
4. push で終わり、CI は待たない（ルートの CLAUDE.md の「判断の線」の持ち主 2026-10-16 の決め）。main の CI が後で赤になったら、点検が最初の手として、赤の原因になった commit（main に入れた物）を git revert で戻す。

## darkfactory を Claude Code から回す

- run の起動・ゲートの答え・resume の打ち方（run_in_background で打つ・nohup や & で切り離さない）は、ルートの CLAUDE.md の「プラグインを作る・直す」に在る（works/ のファイルを読まずに run を打つ会話にも効かせるため）。
- Bash から起動する子プロセスの claude には、対話の認証が継がれない。works/dev の殻には keychain の項目名を環境変数 WORKS_KEYCHAIN_ITEM で渡す（トークンの値は表示も保存もしない。この禁止はルートの CLAUDE.md にも在る）。
- run の中の役が使うアカウントは、コマンドを打った時に読んだ keychain の物に決まる。使用枠が尽きて止まった run は、別のアカウントの項目名で workflow resume すれば、最後に済んだ段の次から続く。
- 起動直後 2 秒の structured_output_missing や first_event_timeout は一過性で、resume で通る。
- 大きい依頼は 1 回の run で半分ほどしか閉じない。続きは 1〜3 項目に分けて出す。
