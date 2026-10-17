# works-dispatch の内部の作り

直す人向け。使い始め方は [README](../README.md)、使う人向けの手順の全部は [SKILL.md](../skills/dispatch/SKILL.md)。

## 全体

自分の番の PR（attention プラグインの `/whose-turn` が、このプラグインを使う人の番として並べる PR）を、枝ごとの作業場（代表の clone〔枝ごとの worktree を作る元にする、ふつうの clone〕の git worktree と、herdr の作業場）に開き、使用率（アカウントの 5 時間と週の利用枠を使った割合）に余裕のあるアカウントの Claude Code で `/catchup <番号>` と、設定のファイルに書いた 2 ターン目の文を送る Claude Code のプラグイン。相手（その PR の自分以外の人。レビュアーや作者）の新しい返事が有れば同じ場所に会話を立て直して送り直し、閉じた PR の場所は片付ける（作業場の一生を 1 つのコマンドで回す）。issue から始める作業も、issue に結んだ枝の作業場を開いて `/catchup <issue の番号>` まで送れる（`--issue N`）。作業ごとの部署（枝の作業場と、そこで働く Claude Code の裏の会話）を立て、頼みのファイルを渡し、herdr に画面を並べることもできる（`--task`）。部署は会社（リポジトリ）ごとのツリー図に出し（`--tree`）、herdr の表示は部署の属性から付け直す（`--sync`）。窓口（人と話し、部署を立てて仕事を渡す、長く生きる Claude Code の会話。dispatch を呼ぶ側）と部署の形は SKILL.md、会社の形の設計は、このリポジトリ（claude-plugins）の根の `docs/specs/2026-10-16-company-shape-design.md`。herdr は、端末を作業場ごとに分けて、中の AI の会話を外から操作できる道具。修正の工場 works（darkfactory）と同じ系列の名前を持つが、中身は works の何も使わない。

- dispatch 自身の判断に AI は使わない（起こした Claude Code の会話は別）。全部 Python の標準ライブラリだけのスクリプト（`dispatch/`）で、`/works-dispatch:dispatch` のスキル（`skills/dispatch/SKILL.md`）はそれを走らせて出力を見せるだけ。
- 設計の正本: [`docs/specs/2026-10-14-catchup-dispatch-design.md`](specs/2026-10-14-catchup-dispatch-design.md)。計画: [`docs/plans/2026-10-14-catchup-dispatch.md`](plans/2026-10-14-catchup-dispatch.md)。
- 変更の記録: [CHANGELOG.md](../CHANGELOG.md)。

## 形（ノードと外への口）

- ノード（`dispatch/nodes/`）は、1 つの仕事と、入出力の JSON（`dispatch/schemas/`）を持つ。ノードは互いを import しない。並べる順を持つのは入口の `dispatch.py` だけ。
  - prs: 自分の番の PR を集める。
  - sessions: 開いている会話を読む。
  - fresh: 自分が作者でレビュアーの付いていない PR を外し、会話の開いている PR を送り直すか決める（相手の新しい返事が有り、会話が手すきで手元の作業が無いときだけ）。会話の開いていない PR も、前に送った後に相手の動きも head の変化も無ければ開き直さない（`no_news`。`--pr` で名指したときは開く）。
  - accounts: アカウントを並べる。週の枠の切り替わりが近い（既定 24 時間以内）ものを先に、それ以外は 5 時間と週の高い方の使用率の低い順、同じなら動いている会話の少ない順。単独でも呼べ、`python3 dispatch/nodes/accounts.py --pick` が 1 つ選んで「名前: 起こし方の命令 — 選んだ訳」の 1 行を出す（`--json` で機械向け）。人が手で会話を立てるときも、dispatch と同じ選び方を通すための口。
  - assign: PR をアカウントと作業場に割り振る。全部の PR は同時に走るので、始める前に、各アカウントの使用率の残りと 1 件あたりの使用率から件数を決める。
  - cost: 1 件あたりの使用率を測って覚える。dispatch が始める前と、全件の `/catchup` が終わった後の 1 回ずつ、使用率を Anthropic の API に問い合わせ（出力 0 トークン）、アカウントごとに、前後の使用率の差（1% 刻みで届くので +1 した上の端）を、今回そのアカウントで開いた件数で割る。statusline から取り込む record は、週の値を、枠が切り替わったときと控えに無いときにしか書かない（放置した会話の古い値で今の値を潰さないための `limits.py` の決まり）。そのため控えの週の値は枠の中で動かず、問い合わせで取る。
  - provision: 枝の場所（代表の clone の git worktree）と herdr の作業場を、無ければ作り、有れば開き直して、origin の head へ早送りする。部署（`--task`）の場所は `prepare_task` が用意し、origin に無い枝も既定の枝から作り、在る場所は git で動かさない。代表の clone 自身がその枝を開いていれば作らない（`branch_busy`）。`--issue` で issue に枝がまだ無ければ、GitHub に枝を作って結ぶ（`gh issue develop`）。
  - launch: Claude Code を起こす。部署は、ペインに名前を付け（`herdr pane rename`）、裏の会話（`--bg --name <名前> --settings <設定のファイル> [--model <モデル>] [--effort <段>] <最初の文>`）として打ち込み（`start_background`）、同じペインで `attach` する。設定のファイルは、役に設定が無ければ `templates/department-settings.json`、有れば役の設定の上に同じ `worktree.bgIsolation = "none"` を重ねて（同じ鍵が役の設定に有っても、こちらが勝つ）部署の `.git` の場所に書いた物。
  - role: 会社の形（リポジトリの `.claude/company.toml`、無ければ設定の置き場の `companies/` の TOML）の `[[roles]]`（役の本文・モデル・effort・起動の設定・納品する要約の必須項目）と `gh_user` を読み、部署を起こすときの設定（`--settings` の JSON）・`--model` と `--effort` の値（`launch_flags`。effort の `inherit` は呼んだ会話の `CLAUDE_EFFORT`）と、フックが足す文を組み立てる。書き方は SKILL.md の「役の中身と起こし方」、設計は会社の形の設計 4.7・4.8。
  - turn: `/catchup` と 2 ターン目の文を送る。1 ターン目の終わりは Claude Code 自身の会話の状態で見る。会話を終える（`/exit`）口も持つ。
  - clean: 代表の clone の linked worktree のうち、消してよい場所を並べる・消す（herdr の worktree の口は手元の枝を残すので、枝は続けて `gitx.delete_branch` で消す）。消してよいのは、PR が閉じていて、会話も手元の作業も無い場所（条件の全部は `dispatch/nodes/clean.py` の冒頭と SKILL.md の `--clean`）。ペインの作業場だけを畳む口（release）も持つ。
  - report: 結果を 1 件 1 行で出す。
  - tree: herdr の作業場と全アカウントの会話が指すリポジトリを会社とし、会社ごとに会社の情報（`.claude/company.toml`、無ければ設定の置き場の `companies/`）と部署（worktree・属性・会話の状態・窓〔その部署の会話を映す herdr のペイン〕）を組み立てる。
  - deliver: 依頼と納品の中身。宛先（「会社/役」か部署の名前）と頼み元の窓を決め、要約の項目（会社の形の `[[roles]]` の `deliver` で役ごとに替えられる。読むのは role）を確かめ、頼み元の会社の共通の `.git` の中の受付箱（`company/inbox/`）に本文と台帳（`log.jsonl`。頼みと納品ごとに、宛先・頼み元・届いたかを 1 行）を置き、窓に 1 行を打ち込む。Stop フックの差し戻しの判定も持つ。
  - sync: 部署の属性から、herdr のペインの名前・表示名（役）・題名（会話の名前）・札（ペインに添える短い印。役・アカウント・上役）を組み立て直す（何度打っても同じ）。
  - land: 部署の成果を本流に入れる決まり（会社の形の `[land]`）を読み、関門の枝へ出して CI の run を待ち、緑で本流が祖先なら本流を早送りして push する。本流が先に進んでいれば merge せずに本流の上への載せ直しを、赤なら失敗の要点を付けて直しを、部署の窓に herdr で頼んで止まる。流れは `landing.py`（[land.md](land.md)）。
  - bump: Claude Code のプラグインの marketplace で、中身を変えたのに版が据え置きのプラグインの版を上げる commit を作る（`docs/releasing.md` の形。会社の形の `[land]` に `bump = "marketplace"` を書いた会社でだけ、`--land` が本流に入れる前に呼ぶ）。
- 部署の属性（役・アカウント・会話の名前と id・上役〔部署を立てた会話〕）は、部署の worktree ごとの git の設定 `company.<名前>`（`extensions.worktreeConfig`）に置く。正本は git で、dispatch は別の台帳を持たない（会社の形の設計 4.2）。読み書きは `gitx.py` の `worktree_attrs`・`enable_worktree_config`・`set_worktree_attr`。
- 外への口は 1 つの道具に 1 ファイル。herdr（`herdr.py`）、git（`gitx.py`）、gh（`ghx.py`）、Claude Code（`claudex.py`）、要る道具の段の点検の tiers（`tierx.py`）、VS Code（`vscode.py`。送り終えた PR の /catchup のページを VS Code のウィンドウにタブで開く）の 6 つ。
  - 場所（git worktree）を作る・並べる・開く・消すのは herdr の worktree の口で、`herdr.py` の `worktrees`・`create_worktree`・`open_worktree`・`remove_worktree` だけが呼ぶ（herdr アダプタ）。ノードは「枝の場所」の言葉だけで書く。置き場は herdr の設定の `worktrees.directory`（既定 `~/.herdr/worktrees/<リポジトリ>/<枝の slug>`）に任せる。
  - worktree は枝と stash を代表の clone と共有するので、手元の作業の判定（`gitx.unpushed`・`gitx.stashed`）は、その場所の HEAD とその枝の物だけを数える。
- 流れの外に、任意の道具が 2 つある。どちらも dispatch の設定のアカウントを読む。
  - `limits.py`: 使用率の控えを作って読む。控えが古いアカウントにだけ API を問い合わせ（probe）、statusline の値を取り込み（record）、herdr のタブ欄に 1 行ずつ出す（show）。取り直しの規則は、持ち主（このプラグインの作者）が先に作った `limits.sh` と `statusline.sh` から写した。herdr がタブ欄のコマンドを打ち切る秒は、herdr の設定の値で、コードの外の雛形 `templates/herdr-tab-bar.toml` に置く。dispatch のコードには期限を足さない（D5）。
    - herdr のタブ欄から呼ぶ道（show と probe）は、設定の TOML を読まず、`herdr-config` が書くアカウントの写し（`<limits_dir>/accounts.json`）を読む。herdr がタブ欄のコマンドに渡す PATH は、ログインのシェルの PATH と違い、macOS では OS に付いてくる Python 3.9 が `python3` になった（2026-10-15 に実物で確かめた）。TOML を読む `tomllib` は 3.11 からなので、そのままでは起動できない。
    - 行には、マシンごとに違う Python の絶対パスを書かない。ほかのプラグインのフックと同じく、PATH の `python3` か `python` を使う。その代わり、タブ欄から呼ぶファイル（`limits.py` と `vendor/claude_auth.py`）は 3.9 の文法で書き、試験（`test_tab_bar_path_reads_as_python_3_9`）が縛る。
  - `activity.py`: Claude Code のフックから、herdr のサイドバーの印 `$act` に作業内容を送る。
- 部署（`--task`）の流れは `dispatch.py` の `_task` だけが持ち、場所・アカウント・起こす・属性は上のノードを使い回す。部署の会話は Claude Code の裏の会話（`claude --bg`）で、置き場と枝を dispatch（herdr 経由）が決めるために、先に herdr に作らせた worktree の中で、`worktree.bgIsolation = "none"` を渡して起こす（Claude Code に worktree を作らせない。WorktreeCreate のフックでも置き場と枝は決められたが、フックはその会話の中の全部の worktree を置き換え、フックの作った worktree は `claude rm` が消さずに断る。2026-10-16 に試した）。部署の片付け（`--clean`）は、会話が終わり枝が本流に入った部署を `claude rm`（`claudex.remove_session`）と herdr の worktree の口で消す。連絡の道（同じアカウントなら SendMessage、違えば窓口が herdr で部署のペインに打ち込み、画面を読む）は、呼んだ会話を `claude agents --json` の一覧から `CLAUDE_CODE_SESSION_ID` で探して決める（`claudex.caller`。Claude Code の文書は、この環境変数を Bash の道具の子に渡し、外の道具と会話を結ぶのに使うと書く）。一覧はアカウントの設定のフォルダごとなので、その識別子が載る一覧のアカウントが呼んだ会話のアカウントである。
- 役の本文は、プラグインの SessionStart のフック（`hooks/hooks.json` → `dispatch/role_hook.py`）が、起動した場所の属性 `company.role` を読んで会話の指示に足す（additionalContext）。部署の属性 `company.gh-user`（立てるときに、dispatch の設定の `[[repos]]` の `gh_user`、無ければ会社の形の `gh_user` を書く。違えば dispatch の設定が勝つ）が有れば、同じフックが Claude Code の `CLAUDE_ENV_FILE` に `export GH_TOKEN="$(gh auth token --user <名前> || echo gh-user-not-logged-in)"` の 1 行を足す（ログインしていないアカウントなら、使えない字を入れて gh を認証の誤りで止め、ほかのアカウントに落とさない）。hooks の文書は、このファイルを Bash の道具のコマンドごとにシェルのコードとして先に走らせると書く（"Each Bash command runs the file's contents as shell code before the command itself"）。そのため鍵の値はどこにも書かれない。起こすコマンドの前に `GH_TOKEN=…` を置く形は、裏の会話に届かなかった（[observed.md](observed.md) の試し）。要確認: `CLAUDE_ENV_FILE` の 1 行で、裏の会話の gh が名指しのアカウントで動くかは、実際に部署を起こしてはまだ確かめていない（[observed.md](observed.md) の試しで確かめたのは、前に置く形が届かないことと、フックの文が会話の頭に入ることだけ）。
- 依頼と納品（`--ask`・`--deliver`）の流れは `dispatch/orders.py` が持つ（`dispatch.py` の流れの続き。ほかの部署と同時に直すため、ぶつからないよう別のファイルにした）。部署が無ければ `_task` で立てる。プラグインの Stop フック（`hooks/hooks.json`）が `orders.py stop` を呼び、部署の会話が受けた頼みを納品せずに止まるのを、上限付きで差し戻す。
- 受付（[受付の設計](specs/2026-10-17-reception-design.md)）: 知らせの待ち受けは `dispatch/wake_hook.py`（プラグインのフックの Stop・SessionStart〔`asyncRewake`〕と UserPromptSubmit〔`--pause`〕）、印・読んだ所・順番待ちは `nodes/wake.py`。`--ask` は待ち受けの居る部署に頼みを順番待ちに積み（`orders.queue_ask`）、`--deliver` は頼み元の待ち受けが居れば台帳に知らせの 1 行を足す。機械窓口の `--call` と `--land` の合図（`[[land.after]]`）の流れは `dispatch/calls.py`、入力の確かめと回す頼みの字は `nodes/tools.py`、道具の欄を読むのは `nodes/role.py`。`calls.py` は会社の形に書かれた道具のコマンドを回すので、subprocess を使ってよい所に入れた（柵 D4）。
- 区切りの印（`--rest`。`orders.rest_here`）は属性 `company.rest`（`nodes/wake.py` の `REST`）。番の終わりの待ち受け（`wake_hook.checker`）が `clear_now` で窓に `/clear` を打って外し、人の文の番の始まり（`wake_hook.resume_from_wait`）でも外す。
- 会社の形が替わったときの表示の揃え直しは `dispatch/shape_hook.py`（プラグインのフックの Stop。裏で走る〔`async`〕）。会社の形の中身の digest を代表の clone の `.git/company/shape-synced` の控えと比べ、違えば `dispatch.sync_companies`（`--sync` の中身）をその会社の分だけ回し、全部付け終えたら控えを書く。
- 柵 D1〜D8 は、試験 `dispatch/tests/test_rules.py` が構文木と文字で見る。中身は設計書の 4 節にある。
  - D1: works（darkfactory）の部品（`works/.shared/` など）を読まない。入れたプラグインはほかのプラグインのフォルダを引けないため。
  - D4: 外へ書く関数は、決まったノードからだけ呼ぶ。対応の表は `dispatch/tests/fences.py` の `WRITES`。
  - D5: 期限（timeout）を足さない。
  - D6: 持ち主の環境の値（アカウント名・パスなど）をコードに書かない。
- attention の `whose-turn.py` と、共通の `scripts/claude_auth.py` は、`dispatch/vendor/` に写して使う。写しは `scripts/shared-copies.py` が正本と同じかを見張る。
- 試験は `python3 -B -m unittest discover -s works-dispatch/dispatch/tests -t .`（リポジトリの根から）。根の `tests/run.sh` もこれを回す。
