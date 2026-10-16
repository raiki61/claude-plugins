# Windows 11（ARM64）の試しの VM

この Mac（Apple Silicon、macOS）の上に、Windows 11 ARM64 の VM を画面の操作なしで作り、Mac から `ssh` で入って Git・Python・gh・herdr・Claude Code を試すための手順と置き場。ライセンス認証はしない（試すだけ）。

## 平易版（3 行）

- 作る・起こす・止める・入るは、全部 `docs/trials/windows-vm/vm.sh` の 1 本で打つ。VM の実体（仮想ディスク・ISO・SSH の鍵）は `~/VMs/win11-arm64/` に在り、リポジトリには入れない。
- VM は画面を出さない QEMU（Homebrew の `qemu`）で動かす。UTM は SSH の中から操れないので使わない。
- Claude Code のトークンは VM の中のファイルに書かない。Mac の keychain から読み、SSH の 1 回ごとに環境変数で渡す。

## 要る物

- Homebrew の `qemu`（`brew install qemu`。UEFI のファームウェア edk2 も一緒に入る）と、Homebrew の Python 3.14（`/opt/homebrew/opt/python@3.14/bin/python3.14`。ISO の URL を得るのに使う）。`vm.sh` は何も自分では入れない。
- `hdiutil`・`ssh`・`security`・`nc` は macOS に初めから在る物を使う。
- 空き容量: ダウンロードが約 9.4 GB、仮想ディスクが道具を入れた後で約 25 GB（最大 96 GB まで伸びる）。合わせて約 35 GB。

## 置き場

VM の実体は `$VM_DIR`（既定 `~/VMs/win11-arm64/`）の下に置く:

- `Win11_arm64.iso`: Windows 11 ARM64 の ISO（Microsoft のダウンロードページの裏の口から）
- `virtio-win.iso`: QEMU の仮想 NIC（virtio-net）を Windows で使うためのドライバー（Fedora の virtio-win）
- `OpenSSH-ARM64.msi`: Windows の機能として OpenSSH のサーバーが入らなかったときの控え（Microsoft の Win32-OpenSSH の GitHub の版）。`vm.sh config` が落とす
- `config.iso`: 無人インストールの応答ファイル（`autounattend.xml`）と、初回に走るスクリプトを詰めた物
- `disk.qcow2`: VM の仮想ディスク（96 GB まで伸びる。Mac の上の大きさは使った分だけ）
- `vars.fd`: VM の UEFI の設定
- `password`: VM の中の利用者 `dev` のパスワード（無人インストールの自動ログオンに使う。SSH では使わない）
- `ssh/id_ed25519`: VM に入るための SSH の鍵（この VM 専用）と `ssh/known_hosts`
- `qemu.pid`・`monitor.sock`・`qemu.log`: 動いている QEMU のプロセス番号・操作の口（QEMU monitor）・ログ
- `screen.png`: `vm.sh screen` が撮った画面

リポジトリの `docs/trials/windows-vm/` の下にあるのは、作るためのスクリプトだけ:

- `vm.sh`: 作る・起こす・止める・入るを打つスクリプト
- `get-iso-url.py`: Microsoft のダウンロードページの裏の口から ISO の URL を得る（Rufus の作者の Fido と同じ手順）
- `autounattend.xml`: Windows を無人で入れる応答ファイル
- `setup.ps1`: 初めてのログオンで OpenSSH のサーバーを開く
- `tools.ps1`: Git・Python・gh・herdr・Claude Code を入れる

## 作り方（初めの 1 回）

コマンドはリポジトリの根で打つ（`vm.sh` は実行権限付き。どこで打っても置き場は `$VM_DIR`）。以下の `vm.sh` は `docs/trials/windows-vm/vm.sh` のこと。

1. `vm.sh fetch` — ISO とドライバーを落とす（約 9.4 GB）。落とし済みの物は飛ばす。Microsoft の口は、短い間に何度も叩くと IP を 1 日ほど止めることがある（止められたら、日を置くか、ブラウザで落とした ISO を `$VM_DIR/Win11_arm64.iso` に置く）。
2. `vm.sh config` — SSH の鍵とパスワードを作り（在れば今の物を使う）、`config.iso` を作り直す。
3. `vm.sh install` — 空の仮想ディスクを作り、Windows を無人で入れ始めて、40 秒ほどで戻る。Windows は裏で自分で何度か再起動し、初めてのログオンで OpenSSH のサーバーを入れて開く。この Mac（M2 Ultra）で SSH が開くまで約 31 分（そのうち約 21 分は、OpenSSH のサーバーを Windows Update から取る時間）。仮想ディスクが既に在ると止まる（入れ直しは下の「やり直す・消す」）。
4. 待つ間の様子は `vm.sh screen` で見る。`$VM_DIR/screen.png` に画面を撮るので、Claude Code に読ませるか、手元に `scp` で持ってきて見る。
5. `vm.sh ssh Get-Date` が日時を返せば SSH が開いている。
6. `vm.sh tools` — Git・Python・gh・herdr・Claude Code を入れる（数分。入っている物は飛ばすので、何度打ってもよい）。Mac に環境変数 `HTTPS_PROXY` があれば、同じプロキシを VM の Claude Code の設定に置く（下の「ネットワークの注意」）。

## 起こす・止める・入る

- 起こす: `vm.sh start`（QEMU は裏で動き、打った SSH を切っても止まらない。SSH が開くまで 20 秒ほど）
- 止める: `vm.sh stop`（Windows にシャットダウンを頼み、QEMU が抜けるのを待つ。20 秒ほど）。固まったときだけ `vm.sh kill`
- 様子: `vm.sh status`。画面は `vm.sh screen`
- 入る: `vm.sh ssh`（PowerShell が開く）。1 つのコマンドだけなら `vm.sh ssh '<PowerShell のコマンド>'`。Mac のシェルに展開させないよう、コマンドは単引用符で囲む
- 端末が要るコマンド（`herdr`・対話の `claude`）を直に起こすなら `vm.sh ssh -t <コマンド>`。`-t` のときはコマンドの中の `"` が消えることがある（Windows の端末の起こし方の都合）ので、`"` を使うコマンドは `-t` なしで打つか、`vm.sh ssh` で入ってから打つ
- Mac を再起動すると VM は止まったまま。使う前に `vm.sh start` を打つ

VM の大きさと置き場は環境変数で替える: `$CPUS`（既定 8）・`$MEM`（既定 16G）・`$DISK_SIZE`（既定 96G。`install` のときだけ効く）・`$SSH_PORT`（既定 2222。Mac の 127.0.0.1 にだけ開く）・`$VM_DIR`（置き場）。どれも覚えておかれないので、既定から替えるなら毎回のコマンドに付ける。2 台目は `VM_DIR=~/VMs/win11-b SSH_PORT=2223 vm.sh ...` のように、`fetch` から `ssh` まで全部に同じ 2 つを付ける（付け忘れると 1 台目を操作する）。

## やり直す・消す

- 入れ直す: `vm.sh kill` の後に `$VM_DIR/disk.qcow2` と `$VM_DIR/vars.fd` を消し、`vm.sh install`。ISO・SSH の鍵・パスワードはそのまま使う。
- 消す: `vm.sh stop` の後に `$VM_DIR` を丸ごと消す。Mac のほかの場所には何も残さない。

## Claude Code の認証

`CLAUDE_ACCOUNT=<名> vm.sh ssh ...` と打つと、Mac の keychain の項目 `claude-code-oauth-<名>` を読み、その SSH の 1 回だけ環境変数 `CLAUDE_CODE_OAUTH_TOKEN` として VM に渡す。

- keychain の項目は、`claude setup-token` で作ったトークンを `security add-generic-password -s claude-code-oauth-<名> -a "$USER" -w` で入れた物（`-w` の後に値を書かないと、値を聞かれる）。この Mac には `default`・`p1`・`p2`・`p3` が既に在る。
- 例: `CLAUDE_ACCOUNT=p1 vm.sh ssh 'claude -p "hello"' </dev/null`（`</dev/null` を付けないと、`claude -p` が標準入力を 3 秒待つ）。対話なら `CLAUDE_ACCOUNT=p1 vm.sh ssh` で入って `herdr` か `claude` を打つ（その SSH の中で起こした物にだけトークンが渡る）。
- 渡し方は SSH の `SendEnv`（Mac 側）と `AcceptEnv CLAUDE_CODE_OAUTH_TOKEN`（VM の `C:\ProgramData\ssh\sshd_config`。`setup.ps1` が書く）。トークンはコマンドの引数に出さないので、Mac の `ps` にも VM のプロセスの引数にも出ない。
- VM の中のファイル（`~\.claude` の下・利用者の環境変数）にトークンは残らない。`$CLAUDE_ACCOUNT` を付けずに入った SSH では `CLAUDE_CODE_OAUTH_TOKEN` は空。
- Microsoft の文書は、Windows に入る OpenSSH では `AcceptEnv` が使えないと書くが、Windows 11 に入る `OpenSSH_for_Windows_9.5p2` で効くことを実測した（2026-10-16）。効かなくなったら、ここを最初に疑う。

## ネットワークの注意（この Mac のネットワークに固有）

- この Mac のネットワークでは、Anthropic のサーバー（claude.ai・api.anthropic.com）に会社のプロキシ経由でしか届かない。`vm.sh tools` は Mac の `HTTPS_PROXY` の値を、VM の Claude Code の設定 `~\.claude\settings.json` の `env`（Claude Code のプロセスにだけ効く環境変数）に HTTPS_PROXY として置く。VM の利用者の環境変数には置かない（置くと herdr のインストーラの `curl.exe` がプロキシ経由で詰まった）。ほかの道具（Git・gh・herdr）はプロキシを通さずに外へ出る。
- Windows の `curl.exe` は証明書の失効を確かめに行き、失効リストに届かないと HTTPS が落ちる。この Mac のネットワークでは、失効リストの置き場（Let's Encrypt・Google）への接続が応答なしで待たされ、「届かないときだけ飛ばす」設定（`ssl-revoke-best-effort`）でも待つ間に時間切れになった。そこで `tools.ps1` が VM の `~\.curlrc` に `ssl-no-revoke`（失効を確かめない。Mac の curl と同じ振る舞い）を書く。herdr のインストーラと `herdr update` が `curl.exe` を使う。
- QEMU のネットワークは IPv6 を切っている（Mac に IPv6 の出口が無いと、Windows の失効確認が IPv6 に行って詰まる）。

## 選んだ道と訳

- ISO の取り方: Microsoft のダウンロードページ（`software-download/windows11arm64`）の裏の口を、Rufus の作者の Fido（`Fido.ps1`）と同じ手順で叩く。quickemu の Mido は Fido の古い手順を写した物で、x64 しか取れず、Microsoft が手順を替えた今は 404 で止まる（2026-10-16 に実測）。
- VM の作り方: UTM の AppleScript と `utmctl` は、画面のあるログインのセッションで UTM が動いていないと答えない（SSH の中からの `utmctl list` は返らなかった）。そこで UTM の中身と同じ QEMU を、Homebrew の物で直に動かす。加速は Apple の Hypervisor.framework（`-accel hvf`）、ディスクは Windows が初めからドライバーを持つ NVMe、NIC は virtio-net（ドライバーを `config.iso` から入れる）、画面は `ramfb`。
- TPM と Secure Boot: QEMU の UEFI（edk2）には Secure Boot が無く、TPM（swtpm）も入れていないので、`autounattend.xml` が Setup の要件の検査を `HKLM\SYSTEM\Setup\LabConfig` のレジストリで飛ばす（quickemu・Rufus と同じ定石）。
- 「Press any key to boot from CD or DVD」: ISO から起動する前に、Windows のブートローダーがキーを待つ。`vm.sh install` が QEMU monitor の `sendkey` で最初の 40 秒「a」を送り続ける。Enter や空白は、始まった Setup の「Cancel」ボタンを押してしまう（この手順を作ったときの 1 回目のインストールで起きた）。
- OpenSSH のサーバー: Microsoft の文書の道（`Add-WindowsCapability` で Windows の機能として入れる）。Windows Update から取るので約 20 分かかる。入らなかったときだけ、`setup.ps1` が自動で `config.iso` の MSI を入れる。Windows の機能が作るファイアウォールの受信の規則は「プライベート」のネットワークにだけ効き、QEMU のネットワークは「パブリック」に分けられるので、`setup.ps1` が規則をどのネットワークにも効かせ、ネットワークをプライベートにする。
- 時計: Windows はハードウェアの時計を地方時として読むので、QEMU に `-rtc base=localtime` を付ける（付けないと 9 時間ずれ、HTTPS の証明書の確認が狂う）。
- ライセンス認証: しない。`autounattend.xml` のプロダクトキーは Windows 11 Pro の汎用のインストール用キー（認証には使えない）。認証していない Windows は、デスクトップに透かしが出て、個人用設定（壁紙など）が変えられないが、試す分の機能と期間には効かない。

## 確かめたこと（2026-10-16）

- Windows 11 Pro ARM64、build 26300（Windows 11 26H2）。SSH の既定のシェルは Windows PowerShell 5.1。
- `vm.sh ssh` の中で: `git --version` → 2.56.0.windows.2、`python --version` → 3.15.0、`gh --version` → 2.102.0、`herdr --version` → 0.9.5（x86_64 の版をエミュレーションで）、`claude --version` → 2.1.301。
- `CLAUDE_ACCOUNT=default vm.sh ssh 'claude -p "Reply with exactly: OK"'` が `OK` を返した。端末付き（`-t`）でもトークンが届いた。
- 作り方の 1〜6 を、別の置き場（2 台目）で初めから通し、手を入れずに同じ結果になった（その 2 台目は確かめた後に消した）。

## 分かっている癖

- コンピューター名は `autounattend.xml` で「WIN11VM」にしたが、今のコンピューター名は「AZ-」（3 文字でこれで全部）。Setup のログ（`C:\Windows\Panther\UnattendGC\setupact.log`）では一度「WIN11VM」が付いている。どこで替わったかは調べていない。SSH には効かない。
