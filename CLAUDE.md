# このリポジトリで作業するエージェントへ

持ち主が決めた、このリポジトリの作業の決まり。会話の記憶（アカウントごとの memory）に頼らず、ここを正とする。

## 会話

- 持ち主との会話は日本語。サブエージェントへの指示は英語でもよいが、持ち主に見せる文は全部日本語。
- 判断してほしいことは冒頭に 1 か所に集める。途中経過の実況は書かない。
- 文（指示ファイル・スキル・ツールの出力・納品の要約）は IT の定着語で書く（ブランチ・ターン・セクション・ゲート・担当者など。持ち主 2026-10-18「節とかITになじみのない言葉を使ってる箇所を置き換えておいて」）。語の一覧は works-dispatch/dispatch/terms.py の TERMS で、直すときは `python3 works-dispatch/dispatch/terms.py --fix <ファイル>` を打ってから差分を読み、意味の変わった所を手で直す。main へ入れるゲートの `python3 scripts/terms.py` は、ファイルごとの当たった件数が基準（scripts/terms-baseline.json）と違えば止まる。減ったときも止まるので、直したら `python3 scripts/terms.py --update` で基準を書き直して一緒に commit する。機械が読む値の決まり（docs/standards/machine-readable-values.md の決まり 3・4）の件数を数える `python3 tests/value-rules.py` も同じゲートで同じ扱いで、件数が基準と違えば止まり、直したら `python3 tests/value-rules.py --update` で基準を書き直して一緒に commit する。会社の形（`.claude/company.toml`）の役「担当」と「作業」の納品（頼み元へ結果を返す要約）の検査（deliver_check）は、定着語でない言い方を含む要約を送らせない。人の言葉やほかの文書の見出しを引くときは「」で囲む（囲んだ中と、`` ` `` の中と、コードブロック〔``` か ~~~ で囲んだ所〕の中は見ない）。
- 英単語は、IT で英語のまま通じる短い語（tmp・main・CI・PR・push・fast-forward など、コマンド・設定の値・業界の呼び名）なら、カタカナに直さずにそのまま書いてよい。カタカナにすると長くなる語は、英語のままか短い英単語を選ぶ（例: 部署の寿命の表示「エフェメラル」を tmp にした）（持ち主 2026-10-29「別に英単語もつかっていいんじゃない？」）。許すのは語だけで、持ち主に見せる文は日本語で書く。英語で通じない和製の語・コンサル英語（アジェンダ・アサイン など）・直訳の横文字は、この許しに入らない。terms.py の TERMS の正しい表記にも、この線で英単語を置く。
- AI だけが読む文は英語で書く。持ち主が読む文は日本語で書く（持ち主 2026-10-29「なんならＡＩ同士の会話は英語にしたほうがいい」「2: おしで」。頼み 79eacf）。AI だけが読む文は、会社の形（`.claude/company.toml`）の役の本文（`[[roles]]` の instructions）と、受け持ち（`[[skills]]` の 1 件。部署が預かるファイルの範囲）の description のうち部署（works-dispatch が仕事ごとに立てる、役を持った別の会話と作業場）の会話にだけ足される物と、works-dispatch のフックが部署の会話へ返す自動の差し戻し（Stop のフックの文など）。持ち主が読む文は、画面・報告・問い・docs・納品の要約（窓口が持ち主へ渡す）・commit のメッセージ・持ち主の画面に出る systemMessage。ツールの出力は今は日本語のまま。英語にした文は、`# terms: english-begin` と `# terms: english-end` の行（印だけのコメントの行）で囲む。区画の中は語の検査（`scripts/terms.py`・works-dispatch/dispatch/terms.py）の対象から外れる。そのかわり、区画の中に日本語の字が残ると赤になる（「」と `` ` `` の中は見ないので、日本語の固有の語はそこに入れる）。閉じの無い区画も赤になる。

## 判断の線

- 人に聞くかは「答えが自明か」で決める。業界の定石（一次の出典が揃う）・元にした graphloops（このリポジトリの別のプラグイン。コードの変更のレビューなどの、結果が変わらなくなるまで回す手順を、会話でなく機械〔エンジン〕が段ごとに回す）と同じ・持ち主が前に決めた事、のどれかで 1 つに決まるなら、根拠を書いて自分で進め、台帳（決めた事と根拠の記録。works の決めは works/docs/owner-decisions.md、組織の改善は docs/reform/ledger.md）に残す。出典が割れる・どれでも決まらない物だけ聞く。
- works は graphloops の review-graph（コードの変更のレビューを機械が段ごとに回す graphloops のスキル）の上位互換を作る。設計は review-graph と能力で比べ、同等か上位互換なら、その設計で人に聞かずに進める。移し替え・作り替えでよく起きる失敗は、元にあった能力を気づかずに削ってしまうこと。削る・置き換える時は、元の能力（keep-essence の 12 の仕組み〔works の作りで外さない仕組みの一覧。中身は works/docs/keep-essence.md〕と、review-graph〔graphloops のスキル。2026-10-19 に消した。最後の形は https://github.com/raiki61/claude-plugins/blob/58c6d08b/graphloops/skills/review-graph/SKILL.md 〕の同じ場面での振る舞い）と照合し、残るかを先に確かめる。残るなら「目的を満たし、全体がより簡潔か」で決めて進め、台帳に残す。元の能力が落ちる物だけ先に聞く。
- graphloops の写しにしない。先に works 自身の事実（配る先・OS・負荷・何が壊れうるか）から要るかを導き、その後で graphloops と比べる。
- 外への書き込み（公開・PR や issue への書き込み・ほかのリポジトリへの push）と取り消せない操作は持ち主に聞く。このリポジトリの部署（works-dispatch が仕事ごとに立てる、役を持った別の会話と作業場。役と受け持ちは会社の形 `.claude/company.toml` に書く）のブランチの push と、main へ入れることは聞かない。main へは works-dispatch の `--land`（部署のブランチを main に入れるコマンド。会社の形 `.claude/company.toml` の `[land]` の `check` をゲートに回し、緑なら fast-forward で push する）で入れる（持ち主 2026-10-16。docs/specs/2026-10-16-company-shape-design.md の 8・docs/releasing.md）。費用のかかる試し・実走は聞かずに回してよい。ただし、確かめの試し（`claude -p` で起動する物。darkfactory〔works の直しを流す工場。下の「darkfactory を Claude Code から回す」〕の run は除く）は、1 つの直し（スキルなら 1 本のスキルかコマンドの直し。commit の数では数えない）につき、1 つの頼みを前の版と直した版に 1 回ずつ頼む 1 対までにし、同じ試しを何度も走らせない（エージェントの振る舞いは回ごとに揺れるので、回数を足しても直しの効き目と揺れを分けられない。確かめは機械の照合〔走らせずに、文が残ったか・指したファイルが在るかなどをコードで照合し、毎回同じ答えが出る物〕を先にする。スキルの分割での形は docs/standards/skill-authoring.md の決まり 8）。1 対より多く走らせたいときは、走らせる前に、何を確かめたいか・何回・見込みの額（1 回の `--max-budget-usd` の額 × 回数）を添えて司令塔（my_notes〔持ち主の、このリポジトリとは別のノートのリポジトリ。works-dispatch の会社の 1 つ〕の、持ち主への中継と部署への頼みの振り分けをする部署。2026-10-24 に社長室・段取りから名前が替わった）に問う（会社の形の部署の会話なら、走らせずに納品〔頼み元へ結果を返すこと。works-dispatch の `--deliver`〕の残った疑問に書き、`--ask my_notes/司令塔` で問いを頼んで、その受付番号を担当者〔その疑問を最後まで追う部署〕にする）。試しの主の止め方は、頼みの文に書く目安（何をしたら止まるか・どこまでで足りるか。例: 最初に読むファイルと最初に打つコマンドを書いたら止まる）にする。`--max-budget-usd` は、目安が外れたときの歯止めとして、ふつうの試しでは当たらない額で付ける（`--max-turns` はターンの数を止めるだけで額を止めない）。上限で止まった回は捨てて走らせ直さず、要るときだけ同じ回を `--resume` で続きから再開する（額・再開の手順は docs/standards/skill-authoring.md の決まり 8）。走らせるアカウントはコマンドに決め打ちせず、起動する直前に使用率の控え（`~/.cache/claude-limits/<アカウント>.json`。works-dispatch が書き、部署を起動するアカウントもこれで選ぶ）を見て、`five_hour` と `seven_day` の `used_percentage` の大きい方が一番小さいアカウントで起動する（控えの無いアカウントは選ばない）（2026-10-18、頼み b7e671 と 009c72。スキルの分割の確かめで 27 回走らせ、アカウントを p1・p2 に決め打ちして p2 の週の枠を 98% まで使った。前の版と直した版の 1 対に絞るのは持ち主の承認〔my_notes の社長室の受付 d543d2〕。docs/reform/ledger.md）。
- タグは作らない（持ち主 2026-09-29「タグはつくりません」）。出荷は main への push で終わり、CI は待たない（持ち主 2026-10-16。CI は main に入った後に回って赤を出す。赤を直すのは点検〔CI とルートの tests/ の受け持ちの部署〕で、最初の手は赤の原因になった commit（main に入れた物）を git revert で戻すこと。docs/adr/0073-land-bumps-and-no-tags.md）。

## プラグインを作る・直す

- README（ルートと各プラグインの `README.md`）は英語の 1 版だけで書き、日本語の版を並べない。スキルとコマンドの名前・説明・本文は日本語のまま（持ち主 2026-10-18。docs/readme-language.md）。
- プラグインを作る・直す前に、docs/standards/README.md の標準の一覧を見て、変える物に当たる標準を読む（一覧の各項目の括弧に何を決めた標準かが書いてある）。
- 特に、各プラグインのスキル（`<プラグイン>/skills/*/SKILL.md`）とコマンド（`<プラグイン>/commands/*.md`）を書く・直す前は docs/standards/skill-authoring.md を読む（本文の長さ・別ファイルへの分け方・description）。

## works（Archon の pack）

works は、コードの直しの頼みを AI の段（調べる・計画する・直す・レビュー・試験など）の流れで回す Claude Code のプラグイン。Archon は YAML に書いた AI の段を順に回すツールで、pack は Archon に載せるワークフローのひとまとまり。流れの本体は darkfactory というワークフロー（中身は works/README.md）。

- works/ は独立した pack。graphloops・convergence-loops の本体は works のために直さず、要素は写して works の側で育てる（写した元の版は works/.shared/core/COPIED_FROM などの台帳に残す）。
- works の直しは darkfactory に流すのが本来の形。危ない直しは run（darkfactory の 1 回の実行。`works/dev/use.sh start` で起動する）を通す。グラフ全体を変える直しは、工場が遅い間の暫定として会話の下請けで作り、本物の run で確かめる（持ち主 2026-10-07・2026-10-09「これは工場が遅いから今暫定的にやってるだけ。工場がよくなったら工場がいい」）。どの道の変更も同じ機械のゲート（考えの住処のチェックと数の歯止め）を CI で通す。考えの住処のチェックは、設計の考え 1 つを持つと決めた 1 か所（住処。一覧は works/docs/concepts.md）の外にその考えが漏れたら赤になる試験。数の歯止めは、住処のまだ無い考えについて、今その考えを知っている所の数が増える差分を赤にする試験。
- ブロック（blk-*）とノードは疎結合に。ノードは darkfactory の 1 つの段で、ブロックは関係するノードをまとめた部品（入口の `blk-entry` など）。線（works/darkfactory/darkfactory.yaml）は、どのブロックをどの順でつなぐかを書いた darkfactory の流れの定義。ブロックの中に他のブロックの名前・出口・振る舞いを書かず、在る前提でも書かない。入力は形（ポート）で述べ、どのブロックが作るかは線（works/darkfactory/darkfactory.yaml）の側に書く。
- 言語: 人と話す所だけその人の言語。言語の選び方の仕組み（自動検出など）は works で作らない（環境・ハーネスに任せる）。
- 作り替えのついでに今ある能力を取りこぼさない（keep-essence の 12 の仕組みは外さない）。期限・タイムアウトを新しく足さない。

## 試験

- リポジトリ全体: bash tests/run.sh（sh では動かない）。works: sh works/tests/run.sh。段は環境変数 WORKS_TESTS で選ぶ（空＝全段、fast、heavy）。
- 手元は速い段とルートのチェックまで。重い段は出荷の CI に任せる（持ち主 2026-10-06「手元の重いのはやめます」）。手元で重い試験を回すのは、触ったモジュールを 1 つずつ（WORKS_TESTS=heavy sh works/tests/run.sh -k <モジュール>）だけ。
- 並べすぎない: pytest の worker は PYTEST_XDIST_AUTO_NUM_WORKERS=4 で抑え、手元の試験は nice -n 19 で回す。
- 変異テスト（tests/mutate.py の本撃ち・mutmut）は撃たない（selfcheck.py は可）。
- サブエージェントに重い試験を回させない。

## 出荷（works の版）

1. 手元の試験は「試験」のセクションと同じく速い段とルートのチェックまで（重い段は main に入った後の CI に任せる）。ルートのチェックは VERSION_BUMP_STRICT=1 を付けて回す（`VERSION_BUMP_STRICT=1 bash tests/run.sh`。版上げの順の検査は main・release/* の CI でだけ厳しくなるため）。
2. CHANGELOG の Unreleased を版に。
3. **版上げ（works の plugin.json・marketplace）を最後の commit にする。** 版上げの後に works を変える commit を積むと main の CI が赤になる（0.2.2 で実測）。
4. push で終わり、CI は待たない（「判断の線」の持ち主 2026-10-16 の決め）。main の CI が後で赤になったら、点検が最初の手として、赤の原因になった commit（main に入れた物）を git revert で戻す。

## darkfactory を Claude Code から回す

- run の起動・ゲートの答え・resume は Bash の run_in_background で打ち、終わりの知らせで次の手を打つ。nohup や & で切り離さない（知らせが来ず、ゲートで止まった run に気づけなかった）。フォアグラウンドで待ち続けない。
- Bash から起動する子プロセスの claude には、対話の認証が継がれない。works/dev の殻には keychain の項目名を環境変数 WORKS_KEYCHAIN_ITEM で渡す（トークンの値は表示も保存もしない）。
- run の中の役が使うアカウントは、コマンドを打った時に読んだ keychain の物に決まる。使用枠が尽きて止まった run は、別のアカウントの項目名で workflow resume すれば、最後に済んだ段の次から続く。
- 起動直後 2 秒の structured_output_missing や first_event_timeout は一過性で、resume で通る。
- 大きい依頼は 1 回の run で半分ほどしか閉じない。続きは 1〜3 項目に分けて出す。

## 手元の操作

- プロセスを止める時は pkill -f の広い形を使わず、pid と cwd を確かめて止める。
- 本社（代表の clone `~/src/claude-plugins`）には main を出しておき、ブランチの作業は worktree でする。本社を直に読む会話（my_notes の司令塔など）が main の今の中身を読めるようにするためで、`--land` が本社の main を fast-forward して中身もそろえるのは、本社に main が出ているときだけ（本社がほかのブランチに居ると main の印だけ進み、本社のファイルは古いまま）（2026-10-18、頼み f38a0a。docs/reform/ledger.md）。
- サブエージェントのモデルは、仕事に適したものを選ぶ。一律に opus を明示しない（持ち主 2026-10-24「適したものを選択するがただしいよ」。前の「opus を明示する」〔持ち主 2026-09-29〕を置き換えた）。
  - 選び方は my_notes の `.claude/AGENTS.md` の「モデル」に倣う。仕様が決まっていて、誤りを後ろの試験やゲートが止める実装・機械的な直しは、能力の低い側（sonnet）でよい。正確さが費用に勝つ判断や、誤りを後ろで止める仕組みの無い仕事は、能力の高い側（opus）にする。web から集めてまとめる所も安いモデルでよい。
  - 定義の有るサブエージェント（inspector・初見の読み手など）は、定義の側のモデルをそのまま使う。照合する役は書いた役と別のモデルにする（my_notes の AGENTS.md）ので、書いた役と定義のモデルが同じときだけ、呼ぶ側で書いた役と違うモデルを指定する。fork（会話を写して起動するサブエージェント）は、モデルを指定せずに会話のモデルを継がせる。
  - 会社の形（`.claude/company.toml`）で役のモデルを下げた部署では、手を動かすサブエージェントはモデルを指定せずに会話のモデルを継がせ、opus にしない（照合する役は上の項のとおり）。中の手だけ opus にすると、部署の費用の半分ほどが opus に残る（docs/model-replay.md の再演で、Sonnet の部署の費用の 47% が opus だった）。根拠は https://claude.com/blog/claude-model-and-effort-level-in-claude-code の "Pick a smaller model when the work is routine."。
- 試しの `claude -p` は、部署の作業場（`git config --worktree` に `company.role` が有る worktree）で起動しない。そこで起動すると works-dispatch のフックが部署の役の本文を足し、試しの会話が本物の役として動く。一時の worktree を切り、その中で `git config --worktree --remove-section company` を打って属性を消し（元の作業場では打たない）、`--settings '{"disableAllHooks":true}' --max-turns 1 --max-budget-usd 1` を付けて起動する（スキルの振る舞いを見る試しでターンが要るときは `--max-turns` を外してよく、止め所は頼みの文に書き、`--max-budget-usd` は歯止めに残す。上限で止まった回の続け方は docs/standards/skill-authoring.md の決まり 8。`git worktree add` は元の作業場の `config.worktree` を写すので、切ったばかりの worktree にも属性が載っている）。本社（代表の clone）は機械で防いである（works-dispatch 0.35.2。名前〔`claude --name`〕の無い会話には役の本文を足さず、動いている窓口の席を `--desk` で取らせない。窓口は本社で持ち主と話して部署に仕事を配る会話で、席はその窓口を名乗れる 1 つの枠。`--desk` は、打った会話をその席に付ける works-dispatch のコマンドで、前の窓口の会話が動いている間はほかの会話から打つと止まる。2026-10-17 に my_notes の本社で試しが窓口として動いたのを受けた直し）ので、本社では起動してよい。
