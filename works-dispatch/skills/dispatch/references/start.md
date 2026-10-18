# 受け持ちを起こす: `--start`・`--due`

受け持ち（`[[skills]]`）に起こし方 `[skills.start]` を書くと、その受け持ちの部署を、窓口の判断に頼らずに周期か命令で起こせる。役の種類は足さない（どの役で起こすかは受け持ちの `role`）。

```toml
[[skills]]
id = "reform"                        # 起こした部署の枝の名前に使う（work/reform-<受付番号の末尾 6 字>）
name = "業務改革"                     # 起こした部署の名前。description は部署の会話の始まりに足される
description = "…"
role = "作業"
[skills.start]
every = "7d"                         # 周期（数と単位 m・h・d・w）。省けば命令でだけ起こす
report_to = "社長室"                  # 納品を返す先の名前（ほかの会社なら「会社/名前」）。起こした者でなくここに返す
brief = "docs/company/reform.md"     # 頼みの本文（リポジトリの中のパス。origin の既定の枝から読む）。text = "…" で直に書いてもよい
by = ["社長室"]                       # --start で起こしてよい会話の名前（省けば誰でも。Claude Code の外から打つ人はいつでも）
```

```
bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --start <受け持ちか 会社/受け持ち> [--dry-run]
bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --due [--dry-run]
```

- 起こし方は `--ask` と同じ宛て方。その名前の常設の部署が在ればその順番待ちに積み、無ければその名前の部署を立てる。一度きりの役（常設でない）の部署は、納品した後、終わりの印（`--done`）か片付け（`--clean --apply`）で畳まれる。前の回の部署がまだ立っていれば、新しく起こさない（同じ名前の部署が 2 つ立つと名前で宛てられなくなる）。
- `--due` は、herdr に開いている会社の受け持ちのうち、前に起こした時から周期が過ぎた物を起こす。過ぎた回が幾つ有っても 1 回だけ起こす（PC が眠っていた間の分を、次の刻みで 1 回に畳む）。一度も起こしていない受け持ちは、次の刻みで起こす。前に起こした時は、受付箱の台帳の `kind: "start"` の行で数える。
- 周期を刻むのは works-dispatch でなく、その人の手元の OS の予定。`--due` を 10 分ごとくらいに打たせる。macOS なら launchd（`~/Library/LaunchAgents/` の plist に `StartInterval` 600 と `ProgramArguments` で上の `--due` の行を書き、`EnvironmentVariables` の `PATH` に herdr と、設定のアカウントを起こすコマンドの置き場を入れる）、Linux なら cron か systemd の timer、Windows ならタスク スケジューラ。Claude Code の予定の機能（`/loop` と CronCreate）は会話が閉じると止まり、7 日で切れるので、刻みには使わない。
- 会社の形に足した起こし方は、本流に入ってから効く。
