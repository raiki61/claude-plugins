# works-dispatch

自分の番の PR（attention プラグインの `/whose-turn` が、このプラグインを使う人の番として並べる PR）を、枝ごとの作業場（代表の clone〔枝ごとの worktree を作る元にする、ふつうの clone〕の git worktree と、herdr の作業場）に開き、使用率（アカウントの 5 時間と週の利用枠を使った割合）に余裕のあるアカウントの Claude Code で `/catchup <番号>` と、設定のファイルに書いた 2 ターン目の文を送る Claude Code のプラグイン。相手（その PR の自分以外の人。レビュアーや作者）の新しい返事が有れば同じ場所に会話を立て直して送り直し、閉じた PR の場所は片付ける（作業場の一生を 1 つのコマンドで回す）。issue から始める作業も、issue に結んだ枝の作業場を開いて `/catchup <issue の番号>` まで送れる（`--issue N`）。作業ごとの部署（枝の作業場と、そこで働く Claude Code の裏の会話）を立て、頼みのファイルを渡し、herdr に画面を並べることもできる（`--task`）。部署は会社（リポジトリ）ごとのツリー図に出し（`--tree`）、herdr の表示は部署の属性から付け直す（`--sync`）。窓口（人と話し、部署を立てて仕事を渡す、長く生きる Claude Code の会話。dispatch を呼ぶ側）と部署の形は SKILL.md、会社の形の設計は枝 `docs/company-shape` の `docs/specs/2026-10-16-company-shape-design.md`。herdr は、端末を作業場ごとに分けて、中の AI の会話を外から操作できる道具。修正の工場 works（darkfactory）と同じ系列の名前を持つが、中身は works の何も使わない。

- dispatch 自身の判断に AI は使わない（起こした Claude Code の会話は別）。全部 Python の標準ライブラリだけのスクリプト（`dispatch/`）で、`/works-dispatch:dispatch` のスキル（`skills/dispatch/SKILL.md`）はそれを走らせて出力を見せるだけ。
- 使う人向けの前提と手順は SKILL.md にまとめた。ここは直す人向けに書く。
- 設計の正本: [`docs/specs/2026-10-14-catchup-dispatch-design.md`](docs/specs/2026-10-14-catchup-dispatch-design.md)。計画: [`docs/plans/2026-10-14-catchup-dispatch.md`](docs/plans/2026-10-14-catchup-dispatch.md)。
- 変更の記録: [CHANGELOG.md](CHANGELOG.md)。

## 形

- ノード（`dispatch/nodes/`）は、1 つの仕事と、入出力の JSON（`dispatch/schemas/`）を持つ。ノードは互いを import しない。並べる順を持つのは入口の `dispatch.py` だけ。
  - prs: 自分の番の PR を集める。
  - sessions: 開いている会話を読む。
  - fresh: 自分が作者でレビュアーの付いていない PR を外し、会話の開いている PR を送り直すか決める（相手の新しい返事が有り、会話が手すきで手元の作業が無いときだけ）。会話の開いていない PR も、前に送った後に相手の動きも head の変化も無ければ開き直さない（`no_news`。`--pr` で名指したときは開く）。
  - accounts: アカウントを並べる。週の枠の切り替わりが近い（既定 24 時間以内）ものを先に、それ以外は 5 時間と週の高い方の使用率の低い順、同じなら動いている会話の少ない順。単独でも呼べ、`python3 dispatch/nodes/accounts.py --pick` が 1 つ選んで「名前: 起こし方の命令 — 選んだ訳」の 1 行を出す（`--json` で機械向け）。人が手で会話を立てるときも、dispatch と同じ選び方を通すための口。
  - assign: PR をアカウントと作業場に割り振る。全部の PR は同時に走るので、始める前に、各アカウントの使用率の残りと 1 件あたりの使用率から件数を決める。
  - cost: 1 件あたりの使用率を測って覚える。dispatch が始める前と、全件の `/catchup` が終わった後の 1 回ずつ、使用率を Anthropic の API に問い合わせ（出力 0 トークン）、アカウントごとに、前後の使用率の差（1% 刻みで届くので +1 した上の端）を、今回そのアカウントで開いた件数で割る。statusline から取り込む record は、週の値を、枠が切り替わったときと控えに無いときにしか書かない（放置した会話の古い値で今の値を潰さないための `limits.py` の決まり）。そのため控えの週の値は枠の中で動かず、問い合わせで取る。
  - provision: 枝の場所（代表の clone の git worktree）と herdr の作業場を、無ければ作り、有れば開き直して、origin の head へ早送りする。部署（`--task`）の場所は `prepare_task` が用意し、origin に無い枝も既定の枝から作り、在る場所は git で動かさない。代表の clone 自身がその枝を開いていれば作らない（`branch_busy`）。`--issue` で issue に枝がまだ無ければ、GitHub に枝を作って結ぶ（`gh issue develop`）。
  - launch: Claude Code を起こす。部署は、ペインに名前を付け（`herdr pane rename`）、裏の会話（`--bg --name <名前> --settings <設定のファイル> [--model <モデル>] <最初の文>`）として打ち込み（`start_background`）、同じペインで `attach` する。設定のファイルは、役に設定が無ければ `templates/department-settings.json`、有れば役の設定の上に同じ `worktree.bgIsolation = "none"` を重ねて（同じ鍵が役の設定に有っても、こちらが勝つ）部署の `.git` の場所に書いた物。
  - role: 会社の形（リポジトリの `.claude/company.toml`、無ければ設定の置き場の `companies/` の TOML）の `[[roles]]`（役の本文・モデル・起動の設定・納品する要約の必須項目）と `gh_user` を読み、部署を起こすときの設定（`--settings` の JSON）と、フックが足す文を組み立てる。書き方は SKILL.md の「役の中身と起こし方」、設計は会社の形の設計 4.7・4.8。
  - turn: `/catchup` と 2 ターン目の文を送る。1 ターン目の終わりは Claude Code 自身の会話の状態で見る。会話を終える（`/exit`）口も持つ。
  - clean: 代表の clone の linked worktree のうち、消してよい場所を並べる・消す（herdr の worktree の口は手元の枝を残すので、枝は続けて `gitx.delete_branch` で消す）。消してよいのは、PR が閉じていて、会話も手元の作業も無い場所（条件の全部は `dispatch/nodes/clean.py` の冒頭と SKILL.md の `--clean`）。ペインの作業場だけを畳む口（release）も持つ。
  - report: 結果を 1 件 1 行で出す。
  - tree: herdr の作業場と全アカウントの会話が指すリポジトリを会社とし、会社ごとに会社の情報（`.claude/company.toml`、無ければ設定の置き場の `companies/`）と部署（worktree・属性・会話の状態・窓）を組み立てる。
  - deliver: 依頼と納品の中身。宛先（「会社/役」か部署の名前）と頼み元の窓を決め、要約の項目（会社の形の `[[roles]]` の `deliver` で役ごとに替えられる。読むのは role）を確かめ、頼み元の会社の共通の `.git` の中の受付箱（`company/inbox/`）に本文と台帳を置き、窓に 1 行を打ち込む。Stop フックの差し戻しの判定も持つ。
  - sync: 部署の属性から、herdr のペインの名前・表示名（役）・題名（会話の名前）・札（ペインに添える短い印。役・アカウント・上役）を組み立て直す（何度打っても同じ）。
  - land: 部署の成果を本流に入れる決まり（会社の形の `[land]`）を読み、関門の枝へ出して CI の run を待ち、緑で本流が祖先なら本流を早送りして push する。本流が先に進んでいれば merge せず、赤なら失敗の要点を付けて、部署の窓に herdr で頼みを打ち込む。流れは `landing.py`（下の「本流に入れる」）。
  - bump: Claude Code のプラグインの marketplace で、中身を変えたのに版が据え置きのプラグインの版を上げる commit を作る（`docs/releasing.md` の形。取り込みのときに上げる会社だけ）。
- 部署の属性（役・アカウント・会話の名前と id・上役）は、部署の worktree ごとの git の設定 `company.<名前>`（`extensions.worktreeConfig`）に置く。正本は git で、dispatch は別の台帳を持たない（会社の形の設計 4.2）。読み書きは `gitx.py` の `worktree_attrs`・`enable_worktree_config`・`set_worktree_attr`。
- 外への口は 1 つの道具に 1 ファイル。herdr（`herdr.py`）、git（`gitx.py`）、gh（`ghx.py`）、Claude Code（`claudex.py`）の 4 つ。
  - 場所（git worktree）を作る・並べる・開く・消すのは herdr の worktree の口で、`herdr.py` の `worktrees`・`create_worktree`・`open_worktree`・`remove_worktree` だけが呼ぶ（herdr アダプタ）。ノードは「枝の場所」の言葉だけで書く。置き場は herdr の設定の `worktrees.directory`（既定 `~/.herdr/worktrees/<リポジトリ>/<枝の slug>`）に任せる。
  - worktree は枝と stash を代表の clone と共有するので、手元の作業の判定（`gitx.unpushed`・`gitx.stashed`）は、その場所の HEAD とその枝の物だけを数える。
- 流れの外に、任意の道具が 2 つある。どちらも dispatch の設定のアカウントを読む。
  - `limits.py`: 使用率の控えを作って読む。控えが古いアカウントにだけ API を問い合わせ（probe）、statusline の値を取り込み（record）、herdr のタブ欄に 1 行ずつ出す（show）。取り直しの規則は、持ち主（このプラグインの作者）が先に作った `limits.sh` と `statusline.sh` から写した。herdr がタブ欄のコマンドを打ち切る秒は、herdr の設定の値で、コードの外の雛形 `templates/herdr-tab-bar.toml` に置く。dispatch のコードには期限を足さない（D5）。
    - herdr のタブ欄から呼ぶ道（show と probe）は、設定の TOML を読まず、`herdr-config` が書くアカウントの写し（`<limits_dir>/accounts.json`）を読む。herdr がタブ欄のコマンドに渡す PATH は、ログインのシェルの PATH と違い、macOS では OS に付いてくる Python 3.9 が `python3` になった（2026-10-15 に実物で確かめた）。TOML を読む `tomllib` は 3.11 からなので、そのままでは起動できない。
    - 行には、マシンごとに違う Python の絶対パスを書かない。ほかのプラグインのフックと同じく、PATH の `python3` か `python` を使う。その代わり、タブ欄から呼ぶファイル（`limits.py` と `vendor/claude_auth.py`）は 3.9 の文法で書き、試験（`test_tab_bar_path_reads_as_python_3_9`）が縛る。
  - `activity.py`: Claude Code のフックから、herdr のサイドバーの印 `$act` に作業内容を送る。
- 部署（`--task`）の流れは `dispatch.py` の `_task` だけが持ち、場所・アカウント・起こす・属性は上のノードを使い回す。部署の会話は Claude Code の裏の会話（`claude --bg`）で、置き場と枝を dispatch（herdr 経由）が決めるために、先に herdr に作らせた worktree の中で、`worktree.bgIsolation = "none"` を渡して起こす（Claude Code に worktree を作らせない。WorktreeCreate のフックでも置き場と枝は決められたが、フックはその会話の中の全部の worktree を置き換え、フックの作った worktree は `claude rm` が消さずに断る。2026-10-16 に試した）。部署の片付け（`--clean`）は、会話が終わり枝が本流に入った部署を `claude rm`（`claudex.remove_session`）と herdr の worktree の口で消す。連絡の道（同じアカウントなら SendMessage、違えば窓口が herdr で部署のペインに打ち込み、画面を読む）は、呼んだ会話を `claude agents --json` の一覧から `CLAUDE_CODE_SESSION_ID` で探して決める（`claudex.caller`。Claude Code の文書は、この環境変数を Bash の道具の子に渡し、外の道具と会話を結ぶのに使うと書く）。一覧はアカウントの設定のフォルダごとなので、その識別子が載る一覧のアカウントが呼んだ会話のアカウントである。
- 役の本文は、プラグインの SessionStart のフック（`hooks/hooks.json` → `dispatch/role_hook.py`）が、起動した場所の属性 `company.role` を読んで会話の指示に足す（additionalContext）。部署の属性 `company.gh-user` が有れば、同じフックが Claude Code の `CLAUDE_ENV_FILE` に `export GH_TOKEN="$(gh auth token --user <名前> || echo gh-user-not-logged-in)"` の 1 行を足す（ログインしていないアカウントなら、使えない字を入れて gh を認証の誤りで止め、ほかのアカウントに落とさない）。hooks の文書は、このファイルを Bash の道具のコマンドごとにシェルのコードとして先に走らせると書く（"Each Bash command runs the file's contents as shell code before the command itself"）。そのため鍵の値はどこにも書かれない。起こすコマンドの前に `GH_TOKEN=…` を置く形は、裏の会話に届かなかった（下の試し）。要確認: `CLAUDE_ENV_FILE` の 1 行で、裏の会話の gh が名指しのアカウントで動くかは、実際に部署を起こしてはまだ確かめていない（下の試しで確かめたのは、前に置く形が届かないことと、フックの文が会話の頭に入ることだけ）。
- 依頼と納品（`--ask`・`--deliver`）の流れは `dispatch/orders.py` が持つ（`dispatch.py` の流れの続き。ほかの部署と同時に直すため、ぶつからないよう別のファイルにした）。部署が無ければ `_task` で立てる。プラグインの Stop フック（`hooks/hooks.json`）が `orders.py stop` を呼び、部署の会話が受けた頼みを納品せずに止まるのを、上限付きで差し戻す。
- 柵 D1〜D8 は、試験 `dispatch/tests/test_rules.py` が構文木と文字で見る。中身は設計書の 4 節にある。
  - D1: works（darkfactory）の部品（`works/.shared/` など）を読まない。入れたプラグインはほかのプラグインのフォルダを引けないため。
  - D4: 外へ書く関数は、決まったノードからだけ呼ぶ。対応の表は `dispatch/tests/fences.py` の `WRITES`。
  - D5: 期限（timeout）を足さない。
  - D6: 持ち主の環境の値（アカウント名・パスなど）をコードに書かない。
- attention の `whose-turn.py` と、共通の `scripts/claude_auth.py` は、`dispatch/vendor/` に写して使う。写しは `scripts/shared-copies.py` が正本と同じかを見張る。
- 試験は `python3 -B -m unittest discover -s works-dispatch/dispatch/tests -t .`（リポジトリの根から）。根の `tests/run.sh` もこれを回す。

## 本流に入れる（`--land`）

`python3 dispatch.py --land <部署>` は、部署（名前か枝の名前で指す）の枝を、会社の形（`.claude/company.toml`、無ければ設定の置き場の `companies/`）の `[land]` の決まりで本流に入れる。会社の形の設計の 8 章（検証をどこで回すか）と 4.10 の 1（部署の畳み方と成果の取り込み）に当たる。流れは入口の一部の `landing.py` が持つ（ほかの部署と同時に `dispatch.py` を触るぶつかりを減らすため、別のファイルにした）。

- 欄:
  - `mode`: 取り込み方。`ff-after-ci`（関門が緑なら本流を早送り）、`pr`（部署の枝を origin に出して PR を出し、止める）、`none`（何もしない）。`[land]` が無ければ `none` で、前の版と同じく何もしない。
  - `gate`: 関門（本流に入れる前に必ず通す検証）。CI の枝の形（固定の頭の後ろに `/*`。例 `release/*`。`*` に部署の名前が入る。できた枝の名前が本流か部署の枝と同じなら止める）か、`check`（手元の検証を `--land` の命令が回す）。
  - `check`: 部署が手元で回す検証のコマンド。`gate = "check"` のときは、`--land` の命令が部署の場所（版を上げるときはその一時の場所）で回す。
  - `bump`: `marketplace` なら、部署は版を上げずに出し、取り込むときに `--land` の命令が版を上げる commit を足してから関門に出す。
  - `main`: 本流の枝。省けば origin の既定の枝。
  - 役ごとに `[land.roles.<役>]` で上の欄を替えられる（役は部署の属性 `company.role`）。
- 順（`ff-after-ci`）:
  1. 本流を取り直す。部署の枝がもう本流に入っていれば、片付けへ進む。
  2. 本流が部署の枝の祖先でなければ（ほかの部署が先に入れた）、関門に出さずに、部署に「本流の上に載せ直して push し直す」と頼んで止める。
  3. `bump` があれば、一時の場所（枝に乗らない worktree）で、部署の枝の先頭の上に版を上げる commit を作る。部署の枝は動かさない。以下、関門に出し、緑なら本流にする commit を「候補」と呼ぶ（版を上げる commit を作ればそれ、作らなければ部署の枝の先頭）。「候補の木」はその commit の中身のファイル。
  4. 関門に出す。CI の枝なら、まず候補の木の GitHub Actions の設定（`.github/workflows`）のどれかがその枝の頭（`release/` など）を書いていることを確かめ（無ければ止める）、その枝へ候補の commit を push して（前の物は上書き）、その commit の run が現れるまで 10 秒おきに見に行き（回数に上限を置かない。期限を足さない決まり D5 のため、上の確かめで代える）、`gh run watch` で終わりを待つ。設定が枝の頭を書いていても、ほかの絞り（変えたファイルの条件など）で run が起きなければ、命令は待ち続ける。そのときは人が命令を止める（Ctrl-C）。watch が途中で戻れば、赤とせずに止める。
  5. 赤なら、部署に失敗の要点（落ちた job と step、記録の終わりの行）を頼んで止める。
  6. 緑なら本流を取り直し、まだ候補の祖先なら、origin の本流を候補へ早送りで push し、手元の本流も早送りし、関門の枝を消す。進んでいれば、部署に載せ直しを頼んで止める。push が断られたら本流を取り直し、先に進んでいたときだけ載せ直しを頼む（枝の保護や認証で断られたなら、頼まずに止める）。2 つの部署が同時に入れようとしても、本流に入る順は早送りで 1 本ずつに決まる。
  7. 入れたら、`--clean` と同じ決まりと部品で部署を片付ける（都度の部署で、会話が終わり、手元の作業が無いとき。常駐の部署は残す）。片付けられない都度の部署（納品の直後で会話がまだ止まりきっていない、など）は、入れた印（属性 `company.landed`。入れた commit）を書いて残し、次の `--land`（どの部署を入れるときでも）が、片付けられる形になっていれば一緒に片付ける（`--clean --apply` でも片付く）。会話が止まるのを待たないのは、期限を足さない決まり D5 のため。都度の部署は `--task` で `--resident` を付けずに立てた部署（属性 `company.residency` が無い部署も都度とみなす）、常駐の部署は `--resident` を付けて立てた部署。
- 部署への頼みは、部署の窓（herdr のペイン）への打ち込みだけ。窓が無ければ、頼みの文を出して呼んだ側に渡させる。頼みと納品の仕組みが入ったら、そちらに替える。
- 終わりの値: 0 は入れた・PR を出した・決まりが `none`。1 は止めた・赤・載せ直しを頼んだ。2 は決まりか引数の誤り。

例（my_notes。検証は `tools/check.py` を手元で回し、通れば早送りで入れる）:

```toml
[land]
mode = "ff-after-ci"
gate = "check"
check = "python3 tools/check.py"
```

例（claude-plugins。部署は変えたプラグインのフォルダの下の試験だけを手元で回し、関門は `release/*` への push で走る CI。版は取り込むときに上げる）:

```toml
[land]
mode = "ff-after-ci"
gate = "release/*"
check = "python3 -B -m unittest discover -s works-dispatch/dispatch/tests -t ."   # 変えたプラグインの試験に替えて回す
bump = "marketplace"
```

## 前提と、なぜ要るか

`dispatch.py --check` が全部確かめる。設定の下書きは `dispatch.py --init --repo OWNER/NAME --source <代表の clone>` が書く。

**要る段: 2**（共通の点検の部品 [tiers](../tiers/README.md) の段。gh・herdr・アカウントの起こし方の命令）。`--check` は最初に `tiers --tier 2 --json` を、設定の各アカウントの起こすコマンドを `--launcher` に渡して呼ぶ（`dispatch/tierx.py`）。足りなければ、その入れ方を出して止まり、下の確かめには進まない。tiers は `plugin.json` の `dependencies` で入り、Claude Code がその `bin/` を PATH に入れる。見つからない（依存の入っていない古い入れ方・Claude Code の外から走らせた）ときは、入れる命令（`claude plugin install tiers@<マーケットプレイス>`）を注記にして下の確かめを続ける。依存は `claude plugin update` では入らないので、tiers を足した版（0.7.0）へ update しただけのときは、この命令で入れる。下の 1 と 3 と 5 は tiers の点検と重なるが、dispatch の普段の回と `--task` の回が使う確かめなので残す。

1. **herdr が動いている。** 手元の版の API に、使う 11 の口（`HERDR_METHODS`。worktree の 4 つを含む）があることと、代表の clone の worktree を並べられることを確かめる。代表の clone は本体の checkout であること（linked worktree でない）も確かめる。
2. **Claude Code の `claude agents --json`。** 開いている会話を、アカウントごとに読む公式の口。同じリポジトリとブランチの会話が開いていれば、その PR は飛ばす。
3. **起こすコマンドと設定のフォルダ。** アカウントごとに、Claude Code を起こすシェルのコマンドと、そのコマンドが `CLAUDE_CONFIG_DIR` に入れるフォルダを書く。コマンドが `CLAUDE_CONFIG_DIR` を入れないなら、`config_dir` は書かない。書くと、信頼の記録と会話の一覧を読む場所がずれる。アカウントを切り替えない人は `accounts` を書かず、`claude` 1 つで動く。
   - `config_dir` を書かないアカウントのフォルダは、作業場のペインで新しく起きるログインのシェルが持つ `CLAUDE_CONFIG_DIR` で決める（`dispatch._login_config_dir`）。無ければ `~/.claude` になる。dispatch を走らせている会話の値は使わない。dispatch はふつう、別のアカウントの会話の中から走るためである。
   - 鍵（そのアカウントの Claude Code のログインのトークン。使うのは `limits.py` の使用率の問い合わせだけ）は共通の `scripts/claude_auth.py` の `account_token` で探す。探す順は 3 段ある。最初は、利用者が作った Keychain の項目（`keychain_service`、無ければフォルダの名前から導いた `claude-code-oauth-<名>`）。次は、Claude Code 自身が置いた Keychain の項目。最後は、フォルダの `.credentials.json`。
   - `limits = false` は、使用率の枠の無いアカウント（Ollama、Foundry など）の印。控えを読まず、取り直さず、使用率で外さない。
4. **`/catchup` を持つプラグイン。** アカウント全体（user）に入れたプラグインのうち、`commands/catchup.md` を持つものを探し、`/<plugin.json の名前>:catchup` を送る。人が画面で `/catchup` と打つと補完がプラグイン名を足すが、herdr は文字をそのまま送るので、名前を組み立てる必要がある。
5. **gh でリポジトリを読める。** 有効なアカウントで読めないリポジトリには、設定に `gh_user` を書く。鍵は `gh auth token --user` で取り出し、gh を呼ぶ子のプロセスにだけ `GH_TOKEN` として渡す。gh にはフォルダごとにアカウントを替える仕組みが無く、`gh auth switch` はマシン全体を替えるので使わない。
6. **代表の clone を、各アカウントで信頼済みにしておく。** Claude Code のフォルダの信頼は、リポジトリの根ごとに記録される。代表の clone の信頼は、そこから作った worktree（別のフォルダ）には効かない。そこで dispatch は、代表の clone を信頼済みのアカウントでだけ、作った worktree にも信頼の印（`.claude.json` の `projects[<根>].hasTrustDialogAccepted`。公式の文書が手で信頼する手として書くもの）を付ける。代表を信頼していないアカウントでは何も書かず、確認がふつうに出る。
7. **手元だけのファイルの置き場（任意）。** `copy_files` に書いた、git が追わないファイル（`.env.local`・`*.local.yaml`・`.claude/settings.local.json` など）を、新しく作った worktree へ写す。写す元は `copy_from` で、省けば代表の clone。
8. **使用率の控え（任意）。** `limits_dir/<アカウント名>.json`。無ければ、そのアカウントは使用率が分からないものとして順の最後に置く。作るのは `limits.py`。
9. **herdr の連携（任意）。** `--check` が `herdr integration status` の claude の行を、アカウントのフォルダごとに読む。herdr の文書によれば、Claude Code の作業中の判定は herdr が画面から読み、連携のフックは会話の識別子を herdr に渡すだけである。そこで、無いときは止めずに、入れるコマンドを出す。
10. **部署の前提（`--task` の回だけ足りない物、ほかの回は注記）。** herdr の API に `pane.rename`・`pane.report_metadata`・`pane.read` が有ること、PATH の `claude --help` に `--name`・`--bg`・`--settings` が有ること。設定に前の版の `task_cwd` が残っていれば、止めずに注記を出して無視する。
11. **古いパス（任意）。** タブ欄の行とサイドバーのフックは、プラグインの版ごとのフォルダを指す。`--check` は、herdr の設定と各アカウントの `settings.json` が、消えた `limits.py` や `activity.py` を指していないかを見る。

持ち主は、herdr の作業中の判定の規則（`~/.config/herdr/agent-detection/claude.toml`）も、手元で上書きしている。この規則はここに入れない。上書きは herdr が配る規則の写しなので、herdr を上げるたびに写し直しが要る。そのうえ、上書きが見る印（背景の作業が残る間に statusline が出す行）は、持ち主の statusline にしか無い。

## 試しの実行で確かめた外の振る舞い（2026-10-14〜2026-10-16）

確かめた版は、herdr 0.9.3、Claude Code 2.1.299、git 2.50.1（Apple Git-155）、gh 2.102.0。項の頭に別の版を書いた物は、その版で確かめた。版が変わったら、ここを確かめ直す。

- herdr の `agent wait` は、まだ会話を見つけていないペインでは待たずに `agent_not_found` を返す。`herdr.wait_ready` は、ペインで前面に動いているプロセス（`pane process-info`）を見て待ち直す。
- herdr の `pane run` は、成功しても何も出力しない。`workspace close` は 2026-10-14 には何も出さず、2026-10-15 には `{"result": {"type": "ok"}}` を返した（どちらも受ける）。
- `herdr agent prompt` で送った `/exit` は、文字は入るが送信されなかった（Enter をもう 1 回押す必要があった）。`/attention:catchup 1737` は 1 回で送信された。違いの理由は調べていない。
- 新しいフォルダで Claude Code を起こすと、信頼の確認が出る。この画面で Esc を押すと、会話は終わらずに進み、そのフォルダが信頼済みとして記録された。
- herdr の worktree の口（2026-10-15 に、一時の git リポジトリに打って確かめた。出力の写しは `dispatch/tests/test_ports.py`）:
  - `worktree list --cwd <元の clone>` は、herdr で開いていないリポジトリに打っても作業場を開かない。`worktree create` は、その元の clone の作業場も開く。
  - 自分の持ち物のリポジトリでは、`worktree create` に `--trust-repository` は要らなかった。
  - `worktree open --path <場所>` だけでは `worktree_not_found` が返り、`--cwd <元の clone>` を足すと開いた。開いている場所に打つと、`already_open: true` でその作業場を返す。
  - `worktree remove --workspace <ID>` は、未追跡のファイルが有ると `dirty_worktree_requires_force` で断る。消すと作業場も閉じ、手元の枝は残る。
  - 元の clone が開いている枝で `worktree create` を打つと、git の「already used by worktree」で `worktree_create_failed` になる。dispatch はその前に `branch_busy` で止める。
- 2026-10-16（Claude Code 2.1.301、herdr 0.9.3）: `herdr pane rename <ペイン> <名前>` は `{"result": {"type": "pane_info", "pane": {…, "label": "<名前>"}}}` を返した。`claude --help` に `-n, --name <name>` が有り、`claude agents --json` の 1 件の `name` に、その名前（付けなければ自動の名前）が出た。持ち主の手元で、別のアカウント（別の `CLAUDE_CONFIG_DIR`）の会話どうしでは SendMessage が両方向とも「No agent named … is reachable」で届かず、各会話の一覧にも同じアカウントの会話しか出なかった（Claude Code の文書は、設定のフォルダの違う会話に届くかを書いていない）。
- 2026-10-16（Claude Code 2.1.301、持ち主の手元のアカウントの 1 つ、使い捨ての clone で部署を 1 つ起こした）: 役の設定（`enabledPlugins` で 10 個のプラグインを切り、`permissions.deny` で Artifact・Workflow・ScheduleWakeup・SendFeedback・ReportFindings を消す）と `--model haiku` を渡すと、最初の要求は 2.10 万トークン（入力 2 + キャッシュの書き 20,977。比べた 4.51 万は、claude-plugins の作業場で絞らずに起こした会話の値で、今回測った物ではなく、持ち主のノートのリポジトリ〔この README の外〕に残る記録から取った。その会話の条件は、dispatch の設定の `accounts` で `main` と名付けたアカウントと Opus 5.5）で、道具の一覧は Agent・AskUserQuestion・Bash・Edit・EnterWorktree・ListAgents・Read・Skill・ToolSearch・Write だけになった。モデルは Haiku 5.5 になった。SessionStart のフックの文は会話の頭に入った。`GH_TOKEN="$(gh auth token --user …)" <アカウントのコマンド> --bg …` と前に置いた鍵は、裏の会話の Bash に届かなかった（`GH_TOKEN` は空で、gh は有効なアカウントのまま）。裏の会話は、起こしたシェルの環境変数を継がない。
- 元の clone の作業場（親）を閉じると、そこから作った worktree の作業場もまとめて閉じることがある（持ち主の herdr の設定の注記は、画面で親を閉じると黙って連鎖すると書き、herdr の issue #3483 を指す。herdr の文書は、CLI の `workspace close --group` が親と linked worktree の作業場をまとめて閉じると書く）。要確認: CLI で `--group` 無しに親を閉じたときの振る舞いは試していない。dispatch は親の作業場を閉じない。

