# このリポジトリで作業するエージェントへ

持ち主が決めた、このリポジトリの作業の決まり。会話の記憶（アカウントごとの memory）に頼らず、ここを正とする。

## 会話

- 持ち主との会話は日本語。サブエージェントへの指示は英語でもよいが、持ち主に見せる文は全部日本語。
- 判断してほしいことは冒頭に 1 か所に集める。途中経過の実況は書かない。

## 判断の線

- 人に聞くかは「答えが自明か」で決める。業界の定石（一次の出典が揃う）・本流（graphloops）と同じ・持ち主が前に決めた事、のどれかで 1 つに決まるなら、根拠を書いて自分で進め、台帳に残す。出典が割れる・どれでも決まらない物だけ聞く。
- works は graphloops の review-graph の上位互換を作る。設計は review-graph と能力で比べ、同等か上位互換なら推しで進める。移し替え・作り替えでよく起きる失敗は、元にあった能力を気づかずに削ってしまうこと。削る・置き換える時は、元の能力（keep-essence の 12 の仕組み〔works/docs/keep-essence.md〕と、review-graph の同じ場面）が残るかを先に照らす。残るなら「目的を満たし、全体がより簡潔か」で決めて進め、台帳に残す。元の能力が落ちる物だけ先に聞く。
- 本流の写しにしない。先に works 自身の事実（配る先・OS・負荷・何が壊れうるか）から要るかを導き、その後で本流と比べる。
- 外への書き込み（公開・PR や issue への書き込み・ほかのリポジトリへの push）と取り消せない操作は持ち主に聞く。このリポジトリの部署の枝の push と、main へ入れることは聞かない。main へは works-dispatch の `--land`（部署の枝を main に入れる命令。会社の形 `.claude/company.toml` の `[land]` の `check` を関門に回し、緑なら早送りで push する）で入れる（持ち主 2026-10-16。docs/specs/2026-10-16-company-shape-design.md の 8・docs/releasing.md）。費用のかかる試し・実走は聞かずに回してよい。
- タグは作らない（持ち主 2026-09-29「タグはつくりません」）。出荷は main への push で終わり、CI は待たない（持ち主 2026-10-16。CI は main に入った後の赤を見つけ、赤なら最初の手は入れた commit を git revert で戻すこと。docs/adr/0073-land-bumps-and-no-tags.md）。

## works（Archon の pack）

- works/ は独立した pack。graphloops・convergence-loops の本体は works のために直さず、要素は写して works の側で育てる（写した元の版は works/.shared/core/COPIED_FROM などの台帳に残す）。
- works の直しは darkfactory に流すのが本来の形。危ない直しは run を通す。グラフ全体を変える直しは、工場が遅い間の暫定として会話の下請けで作り、本物の run で確かめる（持ち主 2026-10-07・2026-10-09「これは工場が遅いから今暫定的にやってるだけ。工場がよくなったら工場がいい」）。どの道の変更も同じ機械の関門（考えの住処の柵と数の歯止め）を CI で通す。
- ブロック（blk-*）と節は疎結合に。ブロックの中に他のブロックの名前・出口・振る舞いを書かず、在る前提でも書かない。入力は形（ポート）で述べ、どのブロックが作るかは線（works/darkfactory/darkfactory.yaml）の側に書く。
- 言語: 人と話す所だけその人の言語。言語の選び方の仕組み（自動検出など）は works で作らない（環境・ハーネスに任せる）。
- 作り替えのついでに今ある能力を取りこぼさない（keep-essence の 12 の仕組みは外さない）。期限・タイムアウトを新しく足さない。

## 試験

- リポジトリ全体: bash tests/run.sh（sh では動かない）。works: sh works/tests/run.sh。段は環境変数 WORKS_TESTS で選ぶ（空＝全段、fast、heavy）。
- 手元は速い段と根の柵まで。重い段は出荷の CI に任せる（持ち主 2026-10-06「手元の重いのはやめます」）。手元で重い試験を回すのは、触ったモジュールを 1 つずつ（WORKS_TESTS=heavy sh works/tests/run.sh -k <モジュール>）だけ。
- 並べすぎない: pytest の worker は PYTEST_XDIST_AUTO_NUM_WORKERS=4 で抑え、手元の試験は nice -n 19 で回す。
- 変異テスト（tests/mutate.py の本撃ち・mutmut）は撃たない（selfcheck.py は可）。
- サブエージェントに重い試験を回させない。

## 出荷（works の版）

1. 手元の試験は「試験」の節と同じく速い段と根の柵まで（重い段は main に入った後の CI に任せる）。根の柵は VERSION_BUMP_STRICT=1 を付けて回す（`VERSION_BUMP_STRICT=1 bash tests/run.sh`。版上げの順の検査は main・release/* の CI でだけ厳しくなるため）。
2. CHANGELOG の Unreleased を版に。
3. **版上げ（works の plugin.json・marketplace）を最後の commit にする。** 版上げの後に works を変える commit を積むと main の CI が赤になる（0.2.2 で実測）。
4. push で終わり、CI は待たない（「判断の線」の持ち主 2026-10-16 の決め）。main の CI が後で赤になったら、最初の手は入れた commit を git revert で戻すこと。

## darkfactory を Claude Code から回す

- run の起動・関所の答え・resume は Bash の run_in_background で起こし、終わりの知らせで次の手を打つ。nohup や & で切り離さない（知らせが来ず、関所で止まった run に気づけなかった）。前景で待って番を持ち続けない。
- Bash から起こす子プロセスの claude には、対話の認証が継がれない。works/dev の殻には keychain の項目名を環境変数 WORKS_KEYCHAIN_ITEM で渡す（トークンの値は表示も保存もしない）。
- run の中の役が使うアカウントは、コマンドを打った時に読んだ keychain の物に決まる。使用枠が尽きて止まった run は、別のアカウントの項目名で workflow resume すれば、最後に済んだ段の次から続く。
- 起動直後 2 秒の structured_output_missing や first_event_timeout は一過性で、resume で通る。
- 大きい依頼は 1 回の run で半分ほどしか閉じない。続きは 1〜3 項目に分けて出す。

## 手元の操作

- プロセスを止める時は pkill -f の広い形を使わず、pid と cwd を確かめて止める。
- サブエージェントは opus を明示する。web から集めてまとめる所だけは sonnet などの安いモデルでもよい（持ち主 2026-09-29。works/docs/owner-decisions.md の「食い違いと解き方」）。
  - ただし、会社の形（`.claude/company.toml`）で役のモデルを下げた部署（今は試し）では、手を動かすサブエージェントにモデルを指定せず、会話のモデルを継がせる。決まった手順の仕事だから下げた部署で、中の手だけ Opus にすると費用の半分ほどが Opus に残る（docs/model-replay.md の再演で 47%）。書いた物を照らす見直しの目（inspector・初見の読み手など）は書いた側と別のモデルにする決まりなので、定義の側のモデルのまま使う（2026-10-17。根拠は my_notes の AGENTS.md の「モデル」と、https://claude.com/blog/claude-model-and-effort-level-in-claude-code の "Pick a smaller model when the work is routine."）。
- 試しの `claude -p` は、部署の作業場（`git config --worktree` に `company.role` が有る worktree）で起こさない。そこで起こすと works-dispatch のフックが部署の役の本文を足し、試しの会話が本物の役として動く。一時の worktree を切り、その中で `git config --worktree --remove-section company` を打って属性を消し（元の作業場では打たない）、`--settings '{"disableAllHooks":true}' --max-turns 1` を付けて起こす（`git worktree add` は元の作業場の `config.worktree` を写すので、切ったばかりの worktree にも属性が載っている）。本社（代表の clone）は機械で防いである（works-dispatch 0.35.2。名前〔`claude --name`〕の無い会話には役の本文を足さず、動いている窓口の席を `--desk` で取らせない。2026-10-17 に my_notes の本社で試しが窓口として動いたのを受けた直し）ので、本社では起こしてよい。
