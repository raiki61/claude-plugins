# 外のツールの口（端末の口と会話の口）の設計

works-dispatch（このリポジトリ claude-plugins の中のプラグインの 1 つ。PR・issue・部署〔works-dispatch が仕事ごとに立てる、役を持った別の会話と作業場〕の仕事を、ブランチごとの作業場と Claude Code の会話に開く）が、herdr（端末を作業場ごとに分けて並べ、中の会話を外から操作できる端末のツール。作業場の中の 1 枚の画面をペインと呼ぶ）と Claude Code（AI と話す会話のツール）の名前やコマンドを直に書いている所を、外への口（外のツールと話す所を目的ごとに 1 つにまとめた窓口。ports and adapters の port）の中に閉じる直しの設計と、それに沿って直した結果の記録。直しは割り振り（下の「出所」）がブランチ `refactor/dispatch-ports` で済ませた。読むのは `works-dispatch/dispatch/` の中で herdr か Claude Code を呼ぶ所を足す・直す人で、直す前に「形」と「チェック D9」のセクションを読む。

出所: 頼み（部署への仕事の依頼 1 件。結果を返すのが納品）20261018-191631-f0a028（本文は my_notes の受付箱 `.git/company/inbox/` の `20261018-191631-f0a028-ask.md`）。my_notes（持ち主〔このリポジトリの持ち主で、works-dispatch を使う人〕の、このリポジトリとは別のノートのリポジトリ）の段取り（部署への頼みを配る部署）が、works-dispatch の直しを受け持つ部署「割り振り」に出した。持ち主の言葉（そのまま。「あれ」は続く文の中身で、「worksdispatch」は works-dispatch のこと。「ロックイン」は特定のツールに頼りきって替えにくいことで、本文では「縛り」と呼ぶ。「アセット」と「フレームワーク」の層の中身は「目的」のセクション）:「あとはあれだな。worksdispatchあたりから、移り変わりの激しいherdrとかclaudecodeにロックインしてる部分があるので、綺麗に作っておこうか。アセットとフレームワークの層を切り分けたり」。前の決め（[catchup-dispatch の設計](2026-10-14-catchup-dispatch-design.md) 49 行。herdr が git worktree〔ブランチごとに別のディレクトリを持つ作業場〕を作る・並べる・消すコマンド（`herdr worktree create` など）を使う訳を「すでにherdrロックインなので」とし、herdr に縛られるのを受け入れた）を改め、縛りを口の中に閉じる。

## 目的

herdr や Claude Code が替わっても、直すのは外への口の裏のアダプタ（`herdr.py`・`claudex.py`）の中だけで済むようにする。部署・頼み・納品のような works-dispatch の考え（持ち主の言う「アセットの層」）は、外のツールの名前・コマンド・環境変数・フックのフィールドを知らない。外のツールと、それに話すアダプタが「フレームワークの層」に当たる。

## 拠り所

- ports and adapters（Alistair Cockburn、https://alistair.cockburn.us/hexagonal-architecture/ ）: アプリケーションは外の技術と、目的ごとの口（port）を通してだけ話し、口の向こうの技術ごとにアダプタを替える。
- 依存の向きの決まり（Robert C. Martin、The Clean Architecture、https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html ）: 内側の層の名前を外側の層が知るのはよいが、逆はいけない。外側の枠組み（ここでは herdr と Claude Code）の名前を内側に書かない。
- 組み立ての 1 か所（composition root。Mark Seemann、https://blog.ploeh.dk/2011/07/28/CompositionRoot/ ）: どの口にどのアダプタを差すかは、入口の近くの 1 か所だけが決める。

## 形

- 口は 2 つ。目的で名付け、ツールの名前で呼ばない。
  - 端末の口 `term`（作業場・ペイン・ブランチの場所を作る・並べる・読む・打ち込む）。今のアダプタは `herdr.py`。
  - 会話の口 `chat`（会話を起動する・並べる・止める・消す、Claude Code に固有の決まり〔会話を空にするコマンド・環境変数・フックの入出力・画面の入力フィールドの読み方〕）。今のアダプタは Claude Code のアダプタ `claudex.py`。名前は `talk` にしなかった（入口の側〔下の項〕の `dispatch`・`move`・`orders`・`wake_hook` が `talk` をローカル変数に使っている）。
- `ports.py` が 2 つの口をどのアダプタが受け持つかを決める 1 か所。口の外（アダプタと `ports.py`・`wiring.py` 以外の `dispatch/` のファイル。入口の側・ノードなど）は `from ports import chat, term` で取り、`import herdr`・`import claudex` を書かない。ツールを替えるときは、同じ名前の関数と値を持つアダプタを書き、`ports.py` の import を替える。口に無い操作を足すときは、アダプタに関数を足して冒頭の口の一覧（ツールの状態を読む関数の「読む口」と、ツールを動かす関数の「書く口」。`herdr.py`・`claudex.py` の冒頭）に載せ、口の外は `term.<関数>`・`chat.<関数>` で呼ぶ。
- アダプタは、使う人に見せる文でツールを呼ぶ名前 `NAME` と、口の操作が失敗したときに上げる例外の型 `Error`（`herdr.py` なら `HerdrError`、`claudex.py` なら `ClaudeError`）を持つ。口の外の文は f-string で `{term.NAME}`・`{chat.NAME}` を埋め込み（例 `f"{term.NAME} のペインを読めない"`）、埋まる値は今のツールの名前（`herdr`・`Claude Code`）なので、今の出力の文は変わらない。
- 部署の窓（部署の会話を映すペイン）を決める決まり（`place_of`・`own_pane`・`holds_talk`・`talk_window`）は works-dispatch の考えなので、`herdr.py` から `windows.py` に移した。2 つの口を組み合わせて決める。
- 入口の側（コマンドやフックから最初に呼ばれる `dispatch.py` と、そこから分けた `orders.py`・`move.py` など、Claude Code のフック〔会話の決まった時点で Claude Code が呼ぶコマンド〕が起動する `*_hook.py`）は、流れ（どのノード〔`dispatch/nodes/` の 1 ファイルが持つ 1 つの仕事〕を、どの順に呼ぶか）を持つ。流れは外への口を、口の束 `Ports` 1 つにまとめて受け取る（`dispatch/tests/` の試験は束を差し替える）。`Ports` と、外のツールの設定を読む関数（`setting_notes` など。herdr の設定ファイルと、アカウントごとの Claude Code の settings.json を読む）は、入口の `dispatch.py` から組み立ての 1 か所 `wiring.py` に移した。`dispatch.Ports` の名前は残す（試験と古い呼び手のため）。
- ノードはほかのノードも入口の側のファイルも import しない決まりで、チェック D3（`dispatch/tests/fences.py` が import を構文木で見る）が見る。今その決まりに背いている所は、チェックが見逃す既知の一覧 `D3_KNOWN`（同じファイル）に載せてある（説明は [internals](../internals.md)〔`docs/internals.md`〕の「形（ノードと外への口）」のセクション）。`nodes/accounts.py` が `dispatch.Ports` を使うために入口の `dispatch.py` を import していた 1 件は、`wiring.py` から取るようにしたので消え、`D3_KNOWN` から外した。

## チェック D9（口の外に書いた外のツールの名前を数える）

`dispatch/tests/fences.py` の `d9_tools_behind_ports` が、構文木で口の外のファイルを見て、外のツールの名前を書いた所を数える。

- 数える物: 識別子（名前・属性・関数・引数・import）のうち herdr か claude を含む物（`claudex` も数える。口の外はアダプタを名指しせず `ports.py` から取る）、文字列の定数（docstring は除く）のうち、ツールの名前・`CLAUDE_*` の環境変数・フックのフィールド（`transcript_path`・`hook_event_name` など）・フックの名前・会話に打つコマンド（`/clear`・`/exit` など）・入力フィールドの印 `❯`・設定のフォルダ（`~/.claude`・`.claude.json`。会社の形の `.claude/company.toml` とプラグインの置き場 `.claude-plugin` は除く）を含む物。
- 数えない所（`LOCKIN_OK`。`D9_KNOWN` と同じく `dispatch/tests/fences.py` に在る）: アダプタ（`herdr.py`・`claudex.py`・`gitx.py`〔git〕・`ghx.py`〔gh〕・`tierx.py`〔tiers プラグイン（このリポジトリの別のプラグイン）の、works-dispatch に要るツールが入っているかの点検〕・`vscode.py`〔VS Code〕）、口の束（`ports.py`）、組み立ての 1 か所（`wiring.py`）、herdr と Claude Code をつなぐこと自体が仕事の部品（Claude Code のアカウントの使用枠の使用率を herdr のタブバーに出す `limits.py`・`limits_entry.py`、Claude Code のフックから herdr のサイドバーへ今の作業を送る `activity.py`）。
- まだ口へ移していない所は、ファイルごとの数 `D9_KNOWN` に載せる。数が増えたら誤り、減ったのに `D9_KNOWN` を直していなくても誤り（`D3_KNOWN` と同じく、直したら一覧から消さないと誤りになる）。
- 数え方: `python3 dispatch/tests/fences.py --lockin` が口の外のファイルごとの数を、`--lockin <ファイル>` が行ごとの所を出す。

## 効き目（数え直した値）

- 出所の頼みに書かれた数（ファイルの数。直す前の値。直した後の効き目は下の D9 の数で見る）: herdr の語を含む .py は 58 本、`claude --bg`・`claude -p`・`claude auth`・`CLAUDE_CONFIG_DIR`・`transcript_path` のどれかを含む .py は 24 本。出所の頼み（f0a028）の文に書かれていた数で、社長室（my_notes の、持ち主への中継の部署）が 2026-10-18 に origin/main の `works-dispatch/dispatch` を git grep で数えた。`works-dispatch/dispatch` の .py 89 本（試験とアダプタも含む）のうち語を含む物の数で、呼び出しか文に出るだけかは見分けていない。下の D9 の数（試験とアダプタを除き、所の数）とは範囲も単位も違うので比べない。
- D9 の数え方（所の数。試験を除く口の外）: 直す前 498 か所（27 本。このリポジトリの main の commit 860eb06f で、このブランチの元）→ 直した後 8 か所（7 本）。

## 層の点検の案 2〜6 のどれを採ったか

前に段取りが割り振りに、dispatch の層の分け方の点検を頼んだ（頼み 20261018-002923-983a64）。その納品（本文は my_notes の受付箱 `.git/company/inbox/` の `20261018-020236-6085ba-deliver.md`）が、層の決まりに背く所を直す案を 1〜6 出した。案 1（チェック D3 が `from nodes import x` の形の import を見逃していた穴を塞ぎ、gh〔GitHub の CLI〕を直に呼ぶ所を gh の口 `ghx.py` へ移す）は、この直しより前に点検の中で済み、works-dispatch 0.59.4 で main に入ったので、ここでは残りの 2〜6 を扱う。採る順は、今回の目的（外のツールへの縛りを口に閉じる）に効く物を先にした。

- 案 3（口の束 `Ports` を入口から出す）: 採った。組み立ての 1 か所 `wiring.py` に出した。会社の形（リポジトリの `.claude/company.toml`。部署の役・受け持ち・main へ入れる前に通すチェック（ゲート）のコマンドなどを書く）に書いたコマンドを回す同じ処理を 3 か所に写した物（`landing.run_check`・`calls.run_tool`・`deliver.gate`）を 1 つにまとめる所は採らなかった。git・gh・会社のツールのコマンドを回す所で、herdr と Claude Code への縛りではないため。
- 案 2（共有の読み取りの置き場）: 一部を採った。口の外にあった部署の窓の決まりを `windows.py` に、入力フィールドの読み方を会話の口に移した。会社の形の読み込み・属性の名前（部署の worktree に `git config --worktree` で付ける `company.role` などの名前）・受付箱（頼みと納品の本文と台帳を置く、頼み元の会社〔頼みを出した部署が居るリポジトリ。works-dispatch は 1 つのリポジトリを 1 つの会社として扱う〕の、worktree が共有する本体の `.git` の中の `company/inbox/`）は外のツールへの縛りではないので、今回は動かさない（ノードがほかのノードを import して関数や値を借りる `D3_KNOWN` の残り 5 件〔借りるファイルと借りられるノードの組で数える〕はそのまま。借りるファイル → 借りられるノードの形で、`nodes/refresh.py` → `role`・`wake`、`nodes/tree.py` → `role`・`start`、`nodes/sync.py` → `role`）。
- 案 6（`wake_hook.py` の中の流れと判断を分け、`nodes/deliver.py` に同居する 6 つの仕事〔宛先・受付箱・要約の検査・依頼と納品の文面づくり・窓への打ち込みと画面の解析・Stop の判定（Claude Code の Stop フック〔会話のターンが終わるときに呼ばれる〕で、納品を済ませずに終えようとした会話を差し戻すか）〕を分ける）: 縛りの所だけ採った。フックの入出力と画面の読み方を会話の口に移した。`wake_hook.py` の流れと判断の分け直しと、`nodes/deliver.py` の仕事ごとの分け直しは縛りではないので、今回はしない。
- 案 4（`orders.py` を仕事ごとに分ける）・案 5（`dispatch.py` を 2 つに分ける）: 採らなかった。どちらも大きく、ほかの部署と同時に触られやすく、縛りの数は減らない（縛りの所は `term.NAME` などの口の値と関数に替えれば済む）。

## まだ口に閉じていない物

- `herdr.py` の中に、Claude Code を知る所が残る（`claude_integration`・作業内容の出所の名前 `claude-activity`）。herdr が Claude Code と組むための機能そのもので、口の中に在る。
- `D9_KNOWN` に残った 8 か所（ファイルごとの内訳は `python3 dispatch/tests/fences.py --lockin`）。どれも口へ移せない訳を `D9_KNOWN` に添えた: 使う人の設定のフィールドの名前 `hide_claude_dir`（3 か所。設定に書いてあるので名前を替えない）、写し（正本のリポジトリ直下の `scripts/claude_auth.py` を、ほかのプラグインと同じく写して持つファイル）の `vendor/claude_auth.py` の名前（2 か所。名前は写しの見張り〔写しが正本と揃っているかを確かめるスクリプト〕`scripts/shared-copies.py` が正本と揃える）、標準ライブラリしか読まない `installed.py`（1 か所）、口を import できなかったときに `shape_hook.py` が出す文（1 か所）、会社の形（上の案 3 の項。部署の役・受け持ち・ゲートのコマンドなどを書くファイル）の置き場 `.claude/company.toml`（1 か所。works-dispatch が決めた置き場で、使う人のリポジトリに在る）。

前にこのセクションに載せていた herdr の JSON のデータの形（`pane_id`・`agent_status`・`agent_session` などのフィールドの名前）を口の外がそのまま読む所は、この文書の本体の直し（ブランチ `refactor/dispatch-ports`）の後に、別の直し（頼み〔上の「出所」〕20261019-082412-dcd5ed、ブランチ `refactor/dispatch-herdr-shape`）で閉じたので、この一覧から外した。中身は次の「herdr の値の形（後の直し）」のセクション。

## herdr の値の形（後の直し）

- 前は、端末の口の読む口のうち `panes`・`agent`・`front_processes` が herdr の JSON をそのまま渡していた（`panes` は `{**p}` で全部のフィールドを素通しし、会話の id は herdr の入れ子 `{"value": …}` のまま）。口の外の `windows.py`・`nodes/deliver.py`・`nodes/tree.py` が入れ子を読み、herdr がフィールドの名前か入れ子を変えると、口の外まで直しが広がった。
- 今は `herdr.py` が、読んだ値を works-dispatch の形に 1 つずつ組み直して渡す（形の一覧は `herdr.py` の冒頭。ペインは `pane_id`・`workspace_id`・`cwd`・`label`・`agent`・`agent_status`・`agent_session`〔会話の id の字〕、会話の情報は `agent`・`agent_status`、前のプロセスは `pid`・`argv`）。`workspaces`・`worktrees`・`create_worktree` などは前から組み直していた。herdr が形を変えても、直すのは `herdr.py` の中だけになる（組み直す関数と、herdr の答えのフィールドを中で読む `wait_ready`・`prompt` などの関数。一覧は `herdr.py` の冒頭）。
- 鍵の名前は herdr の名前と同じ字のまま残した。`--tree --json` の出力（`nodes/tree.py` の `build` が組む。形は `dispatch/schemas/tree.schema.json` で、ペインは `pane_id` を必ず持つと決めている）が部署のペインを `pane_id`・`label`・`agent`・`agent_status`・`agent_session` で出していて、口の外が読むペインの値（部署の行の `panes`）はこの出力と同じ物なので、名前を替えると出力が変わる（この直しの縛りは「動きと出力の文は変えない」）。名前が同じでも、値は口が herdr から 1 つずつ入れた物で、herdr の JSON の素通しではない。前の直し（ブランチ `refactor/dispatch-ports`）の時点で「herdr のフィールドの名前を口の外の 14 本（ファイルの数）・46 か所が読む」と数えた所は、この形を読む所として残り、直していない（この直しでは数え直していない）。
- 縛り: `dispatch/tests/test_ports.py` の `test_panes_hand_the_ports_shape_not_herdrs_json` と `test_agent_and_front_processes_hand_the_ports_shape` が、herdr の JSON に形の外のフィールドと入れ子が有っても、口が形の鍵だけを返すことを見る（素通しに戻すと赤）。試験の偽物のうち、会話の id を herdr の入れ子で組んでいた 5 本（`test_activity`・`test_deliver`・`test_move`・`test_reorg`・`test_wake`）は字に直した。D9 の数（上の「チェック D9」のセクションが数える、口の外に書いた外のツールの名前の所の数。8 か所）は変わらない。
