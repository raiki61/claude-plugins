# 受け持ちを起動する: `--start`・`--due`

受け持ち（`[[skills]]`）に起動方法 `[skills.start]` を書くと、その受け持ちの部署を、窓口の判断に頼らずに周期かコマンドで起動できる。役の種類は足さない（どの役で起動するかは受け持ちの `role`）。

```toml
[[skills]]
id = "reform"                        # 起動した部署のブランチの名前に使う（work/reform-<受付番号の末尾 6 字>）
name = "業務改革"                     # 起動した部署の名前。description は部署の会話の始まりに足される
description = "…"
role = "作業"
[skills.start]
every = "7d"                         # 周期（数と単位 m・h・d・w）。省けばコマンドでだけ起動する
report_to = "社長室"                  # 納品を返す先の名前（ほかの会社なら「会社/名前」）。起動した者でなくここに返す
brief = "docs/company/reform.md"     # 頼みの本文（リポジトリの中のパス。origin の既定のブランチから読む）。text = "…" で直に書いてもよい
by = ["社長室"]                       # --start で起動してよい会話の名前（省けば誰でも。Claude Code の外から打つ人はいつでも）
```

```
bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --start <受け持ちか 会社/受け持ち> [--dry-run]
bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --due [--dry-run]
```

- 起動方法は `--ask` と同じ宛て方。その名前の永続の部署が在ればその順番待ちに積み、無ければその名前の部署を立てる。一度きりの役（永続でない）の部署は、納品した後、終わりの印（`--done`）か片付け（`--clean --apply`）で畳まれる。前の回の部署がまだ立っていれば、新しく起動しない（同じ名前の部署が 2 つ立つと名前で宛てられなくなる）。
- `--due` は、herdr に開いている会社の受け持ちのうち、前に起動した時から周期が過ぎた物を起動する。同じ回で、その会社の台帳のリマインダー（`--remind`。[ask.md](ask.md)）のうち見る時が来てまだ知らせていない物を、立てた会話に 1 度だけ知らせる（`--dry-run` では知らせる物を言うだけ）。過ぎた回が幾つ有っても 1 回だけ起動する（PC が眠っていた間の分を、次の刻みで 1 回に畳む）。一度も起動していない受け持ちは、次の刻みで起動する。前に起動した時は、受付箱の台帳の `kind: "start"` の行で数える。
- 周期を刻むのは頼みと納品。`--ask` と `--deliver` が通るたびに、works-dispatch が `--due` を裏で打つ。裏の `--due` は、その `--ask` か `--deliver` を打った会話から切り離して走り、`--ask` と `--deliver` はその終わりを待たない。出力は打った場所の会社の受付箱の `due.log`（`.git/company/inbox/due.log`）に書き足す。同じ間に 2 つ走っても、会社ごとの錠を持つ方だけが数えて起動し、もう一方はその会社を飛ばすので、同じ受け持ちを 2 度起動しない。`--dry-run` と、順番待ちから取り出して頼み直す `--take … --ask` では打たない。このため、頼みや納品を受けるたびに `--due` を手で打つ要は無い（my_notes の会社では、頼みを配る部署「段取り」が、頼みや納品を受けるたびに手で打っていた）。
- 頼みも納品も来ない間は刻まれない。その間も刻みたい人は、手元の OS の予定に `--due` を 10 分ごとくらいに打たせる。macOS なら launchd（`~/Library/LaunchAgents/` の plist に `StartInterval` 600 と `ProgramArguments` で上の `--due` の行を書き、`EnvironmentVariables` の `PATH` に、herdr と、works-dispatch の設定ファイルに書いたアカウントごとの Claude Code を起動するコマンド（例 `claude-a1`）の置かれたフォルダを入れる。フォルダは `command -v herdr` などで分かる）、Linux なら cron か systemd の timer、Windows ならタスク スケジューラ。Claude Code の予定の機能（`/loop` と CronCreate）は会話が閉じると止まり、7 日で切れるので、刻みには使わない。
- 会社の形に足した起動方法は、メインブランチに入ってから効く。
