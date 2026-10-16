# 初めてのログオンで 1 回だけ走る（autounattend.xml の FirstLogonCommands から）。
# OpenSSH のサーバーを開き、Mac の鍵で入れるようにする。記録は C:\vmsetup.log。
param([string]$Media)
$ErrorActionPreference = 'Continue'
function Log($m) { Write-Output ("[{0:HH:mm:ss}] {1}" -f (Get-Date), $m) }

# 眠らせない（SSH で入る VM なので）
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /hibernate off

# ネットワークが上がるのを待つ（virtio-net のドライバーは specialize の段で入れてある）
for ($i = 0; $i -lt 60; $i++) {
  if (Test-Connection -ComputerName 10.0.2.2 -Count 1 -Quiet) { break }
  Start-Sleep -Seconds 5
}
Log "network: $((Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -like '10.0.2.*').IPAddress)"

# OpenSSH のサーバー: Microsoft の文書の道（Windows の機能として入れる）。だめなら同梱の MSI
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
Log "capability before: $($cap.Name) $($cap.State)"
if ($cap.State -ne 'Installed') {
  try { Add-WindowsCapability -Online -Name $cap.Name -ErrorAction Stop | Out-Null } catch { Log "capability failed: $_" }
}
if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
  $msi = Get-ChildItem "$Media\OpenSSH-*.msi" | Select-Object -First 1
  Log "fallback msi: $msi"
  Start-Process msiexec.exe -Wait -ArgumentList "/i `"$($msi.FullName)`" /qn"
}
Set-Service sshd -StartupType Automatic
Start-Service sshd   # 初めての起動で C:\ProgramData\ssh\sshd_config と鍵が作られる

# 入ったときのシェルを PowerShell に
New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -PropertyType String -Force `
  -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' | Out-Null

# 管理者の利用者の鍵は administrators_authorized_keys に置き、権限を管理者と SYSTEM だけにする
$ak = 'C:\ProgramData\ssh\administrators_authorized_keys'
Copy-Item "$Media\authorized_keys" $ak -Force
icacls.exe $ak /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null

# 鍵の値を VM のファイルに書かずに、SSH の 1 回ごとに環境変数で受け取る
$cfg = 'C:\ProgramData\ssh\sshd_config'
if (-not (Select-String -Path $cfg -Pattern '^AcceptEnv CLAUDE_CODE_OAUTH_TOKEN' -Quiet)) {
  $body = Get-Content $cfg -Raw
  Set-Content -Path $cfg -Encoding ascii -Value ("AcceptEnv CLAUDE_CODE_OAUTH_TOKEN`r`n" + $body)
}
Restart-Service sshd

# Windows の機能が作るファイアウォールの受信の規則は「Private」のネットワークだけに効く。QEMU のネットワークは「Public」に分けられるので、
# 規則をどのネットワークにも効かせ、ネットワークも Private にする（Mac の 127.0.0.1 の 2222 番からしか届かないネットワーク）
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
    -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Profile Any
Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private
Log "sshd: $((Get-Service sshd).Status)"
Log 'done'
