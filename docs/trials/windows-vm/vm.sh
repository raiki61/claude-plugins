#!/bin/bash
# Windows 11 ARM64 の試しの VM を、画面なしの QEMU（Apple の Hypervisor.framework で加速）で作り・起こし・止める。
# 使い方は docs/trials/windows-vm.md。置き場は VM_DIR（既定 ~/VMs/win11-arm64）。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SELF="$HERE/$(basename "$0")"
VM_DIR="${VM_DIR:-$HOME/VMs/win11-arm64}"
PY=/opt/homebrew/opt/python@3.14/bin/python3.14
QEMU=qemu-system-aarch64
FW=/opt/homebrew/share/qemu/edk2-aarch64-code.fd
SSH_PORT="${SSH_PORT:-2222}"
CPUS="${CPUS:-8}"
MEM="${MEM:-16G}"
DISK_SIZE="${DISK_SIZE:-96G}"

cd "$VM_DIR" 2>/dev/null || { mkdir -p "$VM_DIR"; cd "$VM_DIR"; }

mon() { printf '%s\n' "$*" | nc -U -w 2 monitor.sock >/dev/null; }
running() { [ -f qemu.pid ] && kill -0 "$(cat qemu.pid 2>/dev/null)" 2>/dev/null; }

boot() {
  # $1 = install のとき ISO 2 枚を USB の取り外せる媒体として差す
  running && { echo "already running (pid $(cat qemu.pid))"; return 0; }
  # shellcheck disable=SC2054  # 読点は QEMU の引数の中の区切り
  local a=(
    -name win11-arm64
    -machine virt,highmem=on -accel hvf -cpu host -smp "$CPUS" -m "$MEM"
    -rtc base=localtime  # Windows は機械の時計を地方時として読む
    -drive "if=pflash,format=raw,readonly=on,file=$FW"
    -drive "if=pflash,format=raw,file=$VM_DIR/vars.fd"
    -device ramfb
    -device qemu-xhci -device usb-kbd -device usb-tablet
    -drive "if=none,id=disk0,file=$VM_DIR/disk.qcow2,format=qcow2,discard=unmap"
    -device nvme,drive=disk0,serial=win11disk,bootindex=1
    # IPv6 は切る: Mac に IPv6 の出口が無いと、Windows の証明書の失効確認が IPv6 で詰まって HTTPS が落ちる
    -nic "user,model=virtio-net-pci,ipv6=off,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22"
    -display none
    -monitor "unix:$VM_DIR/monitor.sock,server,nowait"
    -pidfile "$VM_DIR/qemu.pid" -daemonize
  )
  if [ "${1:-}" = install ]; then
    # shellcheck disable=SC2054
    a+=(
      -drive "if=none,id=cd0,media=cdrom,readonly=on,file=$VM_DIR/Win11_arm64.iso"
      -device usb-storage,drive=cd0,removable=on,bootindex=0
      -drive "if=none,id=cd1,media=cdrom,readonly=on,file=$VM_DIR/config.iso"
      -device usb-storage,drive=cd1,removable=on
    )
  fi
  "$QEMU" "${a[@]}" 2>>qemu.log
  echo "started (pid $(cat qemu.pid))"
}

case "${1:-}" in
  fetch)  # Windows の ISO（Microsoft のダウンロードの口）と virtio-win（ネットワークのドライバー）を落とす
    [ -f Win11_arm64.iso ] || { url="$("$PY" -I "$HERE/get-iso-url.py" | awk '{print $2}')"; curl -fL --retry 3 -o Win11_arm64.iso "$url"; }
    [ -f virtio-win.iso ] || curl -fL --retry 3 -o virtio-win.iso https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso
    ;;
  config)  # 無人インストールの答えと初回のスクリプトを config.iso に詰める
    mkdir -p ssh && chmod 700 ssh
    [ -f ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N '' -C win11-arm64 -f ssh/id_ed25519
    [ -f password ] || (umask 077; openssl rand -hex 12 > password)
    [ -d cfg ] && chmod -R u+w cfg; rm -rf cfg && mkdir -p cfg/drivers
    sed "s/@PASSWORD@/$(cat password)/g" "$HERE/autounattend.xml" > cfg/autounattend.xml
    cp "$HERE/setup.ps1" cfg/ && cp ssh/id_ed25519.pub cfg/authorized_keys && : > cfg/vmsetup.marker
    mnt="$(mktemp -d)"; hdiutil attach -nobrowse -readonly -mountpoint "$mnt" virtio-win.iso >/dev/null
    cp -R "$mnt/NetKVM/w11/ARM64" cfg/drivers/NetKVM; chmod -R u+w cfg; hdiutil detach "$mnt" >/dev/null; rmdir "$mnt"
    [ -f OpenSSH-ARM64.msi ] || curl -fL -o OpenSSH-ARM64.msi https://github.com/PowerShell/Win32-OpenSSH/releases/download/10.0.0.0p2-Preview/OpenSSH-ARM64-v10.0.0.0.msi
    cp OpenSSH-ARM64.msi cfg/
    rm -f config.iso && hdiutil makehybrid -quiet -iso -joliet -default-volume-name VMSETUP -o config.iso cfg
    rm -rf cfg  # パスワードは password と config.iso だけに残す
    ;;
  install)  # 空の仮想ディスクを作り、ISO から無人で入れる。Setup は終わると自分で再起動し、SSH が開く
    # 入れ直しは仮想ディスクを消してから（Setup はディスクを丸ごと消して入れるので、黙って上書きしない）
    [ -f disk.qcow2 ] && { echo "disk.qcow2 already exists; to reinstall: $SELF kill; rm $VM_DIR/disk.qcow2 $VM_DIR/vars.fd" >&2; exit 1; }
    qemu-img create -q -f qcow2 disk.qcow2 "$DISK_SIZE"
    cp /opt/homebrew/share/qemu/edk2-arm-vars.fd vars.fd
    boot install
    # 「Press any key to boot from CD or DVD」に、最初の 40 秒だけ鍵を送り続ける。
    # Enter や空白だと、始まった Setup の「Cancel」を押してしまうので、ボタンに効かない「a」を送る
    for _ in $(seq 1 40); do mon "sendkey a" || true; sleep 1; done
    echo "installing; watch with: $SELF screen  /  wait for: $SELF ssh Get-Date"
    ;;
  start) boot ;;
  stop)  # Windows に止まるよう頼み、QEMU が抜けるのを待つ
    running || { echo "not running"; exit 0; }
    mon system_powerdown
    for _ in $(seq 1 120); do running || { echo stopped; exit 0; }; sleep 1; done
    echo "still running after 120 s; force: $SELF kill" >&2; exit 1
    ;;
  kill) running && kill "$(cat qemu.pid)"; rm -f qemu.pid ;;
  status) running && echo "running (pid $(cat qemu.pid))" || echo stopped ;;
  screen)  # 画面の写しを PNG で取る（画面を見ずに進み具合を確かめる）
    mon "screendump $VM_DIR/screen.png -f png" && sleep 1 && echo "$VM_DIR/screen.png"
    ;;
  tools)  # Git・Python・gh・herdr・Claude Code を SSH 越しに入れる
    scp -q -i ssh/id_ed25519 -P "$SSH_PORT" -o UserKnownHostsFile="$VM_DIR/ssh/known_hosts" "$HERE/tools.ps1" dev@127.0.0.1:tools.ps1
    # \$HOME は VM の中の PowerShell が開く。プロキシは Mac の HTTPS_PROXY をそのまま渡す（無ければ空）
    "$SELF" ssh "powershell -NoProfile -ExecutionPolicy Bypass -File \$HOME\\tools.ps1 -Proxy '${HTTPS_PROXY:-}'"
    ;;
  ssh)  # ssh で入る。CLAUDE_ACCOUNT を付けると、その keychain の鍵を 1 回だけ環境変数で渡す
    shift
    opts=(-i "$VM_DIR/ssh/id_ed25519" -p "$SSH_PORT" -o StrictHostKeyChecking=accept-new
          -o UserKnownHostsFile="$VM_DIR/ssh/known_hosts" -o ConnectTimeout=5 -o BatchMode=yes)
    [ "${1:-}" = -t ] && { opts+=(-t); shift; }  # コマンドに端末を付ける（herdr・claude を対話で動かすとき）
    if [ -n "${CLAUDE_ACCOUNT:-}" ]; then
      CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s "claude-code-oauth-$CLAUDE_ACCOUNT" -w)"
      export CLAUDE_CODE_OAUTH_TOKEN
      opts+=(-o SendEnv=CLAUDE_CODE_OAUTH_TOKEN)
    fi
    exec ssh "${opts[@]}" dev@127.0.0.1 "$@"
    ;;
  *) echo "usage: $SELF fetch|config|install|tools|start|stop|kill|status|screen|ssh [-t] [cmd...]" >&2; exit 2 ;;
esac
