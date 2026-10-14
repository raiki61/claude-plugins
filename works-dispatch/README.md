# works-dispatch

自分の番の PR を、PR ごとの作業場（代表の clone から作る clone と、herdr の作業場）に開き、使用率に余裕のあるアカウントの Claude Code で `/catchup <番号>` と、設定のファイルに書いた 2 ターン目の文を送る Claude Code のプラグイン。herdr は、端末を作業場ごとに分けて、中の AI の会話を外から操作できる道具。修正の工場 works（darkfactory）と同じ系列の名前を持つが、中身は works の何も使わない。

- AI は使わない。全部 Python の標準ライブラリだけのスクリプト（`dispatch/`）で、`/works-dispatch:dispatch` のスキル（`skills/dispatch/SKILL.md`）はそれを走らせて出力を見せるだけ。
- 使う人向けの前提と手順は SKILL.md にまとめた。ここは直す人向けに書く。
- 設計の正本: [`docs/specs/2026-10-14-catchup-dispatch-design.md`](docs/specs/2026-10-14-catchup-dispatch-design.md)。計画: [`docs/plans/2026-10-14-catchup-dispatch.md`](docs/plans/2026-10-14-catchup-dispatch.md)。
- 変更の記録: [CHANGELOG.md](CHANGELOG.md)。

## 形

- ノード（`dispatch/nodes/`）は、1 つの仕事と、入出力の JSON（`dispatch/schemas/`）を持つ。ノードは互いを import しない。並べる順を持つのは入口の `dispatch.py` だけ。
  - prs: 自分の番の PR を集める。
  - sessions: 開いている会話を読む。
  - accounts: アカウントを使用率で並べる。
  - assign: PR をアカウントと作業場に割り振る。
  - provision: clone と herdr の作業場を、無ければ作り、有れば使い直す。
  - launch: Claude Code を起こす。
  - turn: `/catchup` と 2 ターン目の文を送る。
  - clean: 消してよい作業場を並べる・消す。
  - report: 結果を 1 件 1 行で出す。
- 外への口は 1 つの道具に 1 ファイル。herdr（`herdr.py`）、git（`gitx.py`）、gh（`ghx.py`）、Claude Code（`claudex.py`）の 4 つ。
- 流れの外に、任意の道具が 2 つある。どちらも dispatch の設定のアカウントを読む。
  - `limits.py`: 使用率の控えを作って読む。控えが古いアカウントにだけ API を問い合わせ（probe）、statusline の値を取り込み（record）、herdr のタブ欄に 1 行ずつ出す（show）。取り直しの規則は、持ち主が先に作った `limits.sh` と `statusline.sh` から写した。herdr の打ち切りの秒は、コードの外の雛形 `templates/herdr-tab-bar.toml` に置く（D5）。
  - `activity.py`: Claude Code のフックから、herdr のサイドバーの印 `$act` に作業内容を送る。
- 柵 D1〜D8 は、試験 `dispatch/tests/test_rules.py` が構文木と文字で見る。中身は設計書の 4 節にある。
  - D1: works（darkfactory）の部品（`works/.shared/` など）を読まない。入れたプラグインはほかのプラグインのフォルダを引けないため。
  - D4: 外へ書く関数は、決まったノードからだけ呼ぶ。
  - D5: 期限（timeout）を足さない。
  - D6: 持ち主の環境の値（アカウント名・パスなど）をコードに書かない。
- attention の `whose-turn.py` と、共通の `scripts/claude_auth.py` は、`dispatch/vendor/` に写して使う。写しは `scripts/shared-copies.py` が正本と同じかを見張る。
- 試験は `python3 -B -m unittest discover -s works-dispatch/dispatch/tests -t .`（リポジトリの根から）。根の `tests/run.sh` もこれを回す。

## 前提と、なぜ要るか

`dispatch.py --check` が全部確かめる。設定の下書きは `dispatch.py --init --repo OWNER/NAME --source <代表の clone>` が書く。

1. **herdr が動いている。** 手元の版の API に、使う 7 つの口（`HERDR_METHODS`）があることを確かめる。
2. **Claude Code の `claude agents --json`。** 開いている会話を、アカウントごとに読む公式の口。同じリポジトリとブランチの会話が開いていれば、その PR は飛ばす。
3. **起こすコマンドと設定のフォルダ。** アカウントごとに、Claude Code を起こすシェルのコマンドと、そのコマンドが `CLAUDE_CONFIG_DIR` に入れるフォルダを書く。コマンドが `CLAUDE_CONFIG_DIR` を入れないなら、`config_dir` は書かない。書くと、信頼の記録と会話の一覧を読む場所がずれる。アカウントを切り替えない人は `accounts` を書かず、`claude` 1 つで動く。
   - `config_dir` を書かないアカウントのフォルダは、作業場のペインで新しく起きるログインのシェルが持つ `CLAUDE_CONFIG_DIR` で決める（`dispatch._login_config_dir`）。無ければ `~/.claude` になる。dispatch を走らせている会話の値は使わない。dispatch はふつう、別のアカウントの会話の中から走るためである。
   - 鍵は共通の `scripts/claude_auth.py` の `account_token` で探す。探す順は 3 段ある。最初は、利用者が作った Keychain の項目（`keychain_service`、無ければフォルダの名前から導いた `claude-code-oauth-<名>`）。次は、Claude Code 自身が置いた Keychain の項目。最後は、フォルダの `.credentials.json`。
   - `limits = false` は、使用率の枠の無いアカウント（Ollama、Foundry など）の印。控えを読まず、取り直さず、使用率で外さない。
4. **`/catchup` を持つプラグイン。** アカウント全体（user）に入れたプラグインのうち、`commands/catchup.md` を持つものを探し、`/<plugin.json の名前>:catchup` を送る。人が画面で `/catchup` と打つと補完がプラグイン名を足すが、herdr は文字をそのまま送るので、名前を組み立てる必要がある。
5. **gh でリポジトリを読める。** 有効なアカウントで読めないリポジトリには、設定に `gh_user` を書く。鍵は `gh auth token --user` で取り出し、gh を呼ぶ子のプロセスにだけ `GH_TOKEN` として渡す。gh にはフォルダごとにアカウントを替える仕組みが無く、`gh auth switch` はマシン全体を替えるので使わない。
6. **代表の clone を、各アカウントで信頼済みにしておく。** Claude Code のフォルダの信頼は、リポジトリの根ごとに記録される。親のフォルダの信頼は、中の clone には効かない。そこで dispatch は、代表の clone を信頼済みのアカウントでだけ、作った clone にも信頼の印（`.claude.json` の `projects[<根>].hasTrustDialogAccepted`。公式の文書が手で信頼する手として書くもの）を付ける。代表を信頼していないアカウントでは何も書かず、確認がふつうに出る。
7. **手元だけのファイルの置き場（任意）。** `copy_files` に書いた、git が追わないファイル（`.env.local`・`*.local.yaml`・`.claude/settings.local.json` など）を、新しい clone へ写す。写す元は `copy_from` で、省けば代表の clone。
8. **使用率の控え（任意）。** `limits_dir/<アカウント名>.json`。無ければ、そのアカウントは使用率が分からないものとして順の最後に置く。作るのは `limits.py`。
9. **herdr の連携（任意）。** `--check` が `herdr integration status` の claude の行を、アカウントのフォルダごとに読む。herdr の文書によれば、Claude Code の作業中の判定は herdr が画面から読み、連携のフックは会話の識別子を herdr に渡すだけである。そこで、無いときは止めずに、入れるコマンドを出す。
10. **古いパス（任意）。** タブ欄の行とサイドバーのフックは、プラグインの版ごとのフォルダを指す。`--check` は、herdr の設定と各アカウントの `settings.json` が、消えた `limits.py` や `activity.py` を指していないかを見る。

持ち主は、herdr の作業中の判定の規則（`~/.config/herdr/agent-detection/claude.toml`）も、手元で上書きしている。この規則はここに入れない。上書きは herdr が配る規則の写しなので、herdr を上げるたびに写し直しが要る。そのうえ、上書きが見る印（背景の作業が残る間に statusline が出す行）は、持ち主の statusline にしか無い。

## 試しの実行で確かめた外の振る舞い（2026-10-14）

確かめた版は、herdr 0.9.3、Claude Code 2.1.299、git 2.50.1（Apple Git-155）。版が変わったら、ここを確かめ直す。

- herdr の `agent wait` は、まだ会話を見つけていないペインでは待たずに `agent_not_found` を返す。`herdr.wait_ready` は、ペインの前のプロセス（`pane process-info`）を見て待ち直す。
- herdr の `pane run` と `workspace close` は、成功しても何も出力しない。
- `herdr agent prompt` で送った `/exit` は、文字は入るが送信されなかった（Enter をもう 1 回押す必要があった）。`/attention:catchup 1737` は 1 回で送信された。違いの理由は調べていない。
- 新しいフォルダで Claude Code を起こすと、信頼の確認が出る。この画面で Esc を押すと、会話は終わらずに進み、そのフォルダが信頼済みとして記録された。
- `git clone` が、ローカルの clone でまれに `BUG: refs/files-backend.c:3050: initial ref transaction called with existing refs` で落ち、`.git` だけの作りかけを残す（20 回ほどのうち数回）。provision は作りかけを消して 1 回だけやり直す。原因は突き止めていない。

