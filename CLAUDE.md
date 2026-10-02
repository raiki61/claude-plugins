# このリポジトリで作業するエージェントへ

持ち主が決めた、このリポジトリの作業の決まり。会話の記憶（アカウントごとの memory）に頼らず、ここを正とする。

## 会話

- 持ち主との会話は日本語。サブエージェントへの指示は英語でもよいが、持ち主に見せる文は全部日本語。
- 判断してほしいことは冒頭に 1 か所に集める。途中経過の実況は書かない。

## 判断の線

- 人に聞くかは「答えが自明か」で決める。業界の定石（一次の出典が揃う）・本流（graphloops）と同じ・持ち主が前に決めた事、のどれかで 1 つに決まるなら、根拠を書いて自分で進め、台帳に残す。出典が割れる・どれでも決まらない物だけ聞く。
- works は graphloops の review-graph の上位互換を作る。設計は review-graph と能力で比べ、同等か上位互換なら推しで進める。移し替え・作り替えでよく起きる失敗は、元にあった能力を気づかずに削ってしまうこと。削る・置き換える時は、元の能力（keep-essence の 11 の仕組み〔works/docs/keep-essence.md〕と、review-graph の同じ場面）が残るかを先に照らす。残るなら「目的を満たし、全体がより簡潔か」で決めて進め、台帳に残す。元の能力が落ちる物だけ先に聞く。
- 本流の写しにしない。先に works 自身の事実（配る先・OS・負荷・何が壊れうるか）から要るかを導き、その後で本流と比べる。
- 外への書き込み（merge・push・公開）と取り消せない操作は聞く。費用のかかる試し・実走は聞かずに回してよい。
- タグは人が作って push する。

## works（Archon の pack）

- works/ は独立した pack。graphloops・convergence-loops の本体は works のために直さず、要素は写して works の側で育てる（写した元の版は works/.shared/core/COPIED_FROM などの台帳に残す）。
- works の直しは全部 darkfactory 自身に流す（自分食い）。hotfix も例外にしない。
- ブロック（blk-*）と節は疎結合に。ブロックの中に他のブロックの名前・出口・振る舞いを書かず、在る前提でも書かない。入力は形（ポート）で述べ、どのブロックが作るかは線（works/darkfactory/darkfactory.yaml）の側に書く。
- 言語: 人と話す所だけその人の言語。言語の選び方の仕組み（自動検出など）は works で作らない（環境・ハーネスに任せる）。
- 作り替えのついでに今ある能力を取りこぼさない（keep-essence の 11 の仕組みは外さない）。期限・タイムアウトを新しく足さない。

## 試験

- リポジトリ全体: bash tests/run.sh（sh では動かない）。works: sh works/tests/run.sh。段は環境変数 WORKS_TESTS で選ぶ（空＝全段、fast、heavy）。
- works に入れる前に全段を通す（速い段だけで通した直しが、取り込んだ後の全段で赤を出した実測がある）。重い試験は作業中の枝を GitHub に push して CI に任せてよい。
- 並べすぎない: pytest の worker は PYTEST_XDIST_AUTO_NUM_WORKERS=4 で抑え、手元の試験は nice -n 19 で回す。
- 変異テスト（tests/mutate.py の本撃ち・mutmut）は撃たない（selfcheck.py は可）。
- サブエージェントに重い試験を回させない。

## 出荷（works の版）

1. 全段の試験（手元でも VERSION_BUMP_STRICT=1 で回す。版上げの順の検査は main・release/* の CI でだけ厳しくなるため）。
2. CHANGELOG の Unreleased を版に。
3. **版上げ（works の plugin.json・marketplace）を最後の commit にする。** 版上げの後に works を変える commit を積むと main の CI が赤になる（0.2.2 で実測）。
4. push の後に gh run list で CI の緑を確かめる。

## darkfactory を Claude Code から回す

- run の起動・関所の答え・resume は Bash の run_in_background で起こし、終わりの知らせで次の手を打つ。nohup や & で切り離さない（知らせが来ず、関所で止まった run に気づけなかった）。前景で待って番を持ち続けない。
- Bash から起こす子プロセスの claude には、対話の認証が継がれない。works/dev の殻には keychain の項目名を環境変数 WORKS_KEYCHAIN_ITEM で渡す（トークンの値は表示も保存もしない）。
- run の中の役が使うアカウントは、コマンドを打った時に読んだ keychain の物に決まる。使用枠が尽きて止まった run は、別のアカウントの項目名で workflow resume すれば、最後に済んだ段の次から続く。
- 起動直後 2 秒の structured_output_missing や first_event_timeout は一過性で、resume で通る。
- 大きい依頼は 1 回の run で半分ほどしか閉じない。続きは 1〜3 項目に分けて出す。

## 手元の操作

- プロセスを止める時は pkill -f の広い形を使わず、pid と cwd を確かめて止める。
- サブエージェントは全部 opus を明示する（sonnet 以下は使わない）。
