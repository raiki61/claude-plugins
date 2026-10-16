# SSH の中で 1 回走らせ、Git・Python・gh・herdr・Claude Code を入れる（vm.sh tools から）。
# どれも公式のダウンロード元から、画面を出さない形で入れる。入っている物は飛ばす。
# -Proxy: Mac が使う HTTP のプロキシ（vm.sh tools が Mac の HTTPS_PROXY を渡す）。Claude Code にだけ使う。
param([string]$Proxy)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$dl = "$env:TEMP\vmtools"; New-Item -ItemType Directory -Force $dl | Out-Null

function Asset($repo, $pattern) {
  $r = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'vmtools' }
  ($r.assets | Where-Object name -match $pattern | Select-Object -First 1).browser_download_url
}
function Fetch($url) { $f = Join-Path $dl (Split-Path $url -Leaf); Invoke-WebRequest $url -OutFile $f; $f }
# WindowsApps の下の python.exe は Microsoft Store を開くだけの偽物なので、居ないものとみなす
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue | Where-Object Source -notlike '*\WindowsApps\*') }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

if (-not (Have git)) {
  Write-Output 'git: installing'
  $f = Fetch (Asset 'git-for-windows/git' '^Git-[\d.]+-arm64\.exe$')
  Start-Process $f -Wait -ArgumentList '/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', '/SUPPRESSMSGBOXES'
}
if (-not (Have python)) {
  Write-Output 'python: installing'
  # python.org の版の一覧から、ARM64 の Windows の installer が在る一番新しい 3.x を選ぶ
  $vers = (Invoke-WebRequest 'https://www.python.org/ftp/python/' -UseBasicParsing).Links.href |
    Where-Object { $_ -match '^3\.\d+\.\d+/$' } | ForEach-Object { [version]$_.TrimEnd('/') } | Sort-Object -Descending
  foreach ($v in $vers) {
    $u = "https://www.python.org/ftp/python/$v/python-$v-arm64.exe"
    try { Invoke-WebRequest $u -Method Head -UseBasicParsing | Out-Null; break } catch { $u = $null }
  }
  $f = Fetch $u
  Start-Process $f -Wait -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0'
}
if (-not (Have gh)) {
  Write-Output 'gh: installing'
  $f = Fetch (Asset 'cli/cli' '_windows_arm64\.msi$')
  Start-Process msiexec.exe -Wait -ArgumentList '/i', "`"$f`"", '/qn'
}
Refresh-Path
# Windows の curl.exe（Schannel）は証明書の失効を確かめに行き、失効リストに届かないと落ちる。この Mac のネットワークでは
# 失効リストの置き場（Let's Encrypt・Google）への接続が応答なしで待たされ、「届かないときだけ飛ばす」でも待つ間に
# 時間切れになる。Mac の curl と同じく失効を確かめない。herdr の installer と herdr update が curl.exe を使う
$rc = "$HOME\.curlrc"
if (-not ((Test-Path $rc) -and (Select-String -Path $rc -Pattern '^ssl-no-revoke' -Quiet))) {
  Add-Content -Path $rc -Encoding ascii -Value 'ssl-no-revoke'
}
if (-not (Have herdr)) {
  Write-Output 'herdr: installing'
  & ([scriptblock]::Create((Invoke-RestMethod https://herdr.dev/install.ps1)))
}
# この Mac のネットワークでは、Anthropic のサーバーに会社のプロキシ経由でしか届かない。プロキシは Claude Code の
# 入れ方と Claude Code 自身にだけ効かせる（利用者の環境変数に置くと、herdr の installer の curl.exe がプロキシ経由で詰まる）
if ($Proxy) {
  $env:HTTPS_PROXY = $Proxy; $env:NO_PROXY = 'localhost,127.0.0.1'
  [System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy($Proxy)
}
if (-not (Have claude)) {
  Write-Output 'claude: installing'
  # 子のスコープで走らせる（installer が宣言する Set-StrictMode をこのスクリプトに漏らさない）
  & ([scriptblock]::Create((Invoke-RestMethod https://claude.ai/install.ps1)))
}
if ($Proxy) {
  # Claude Code の設定（~\.claude\settings.json）の env は、Claude Code の process にだけ環境変数として効く
  $sf = "$HOME\.claude\settings.json"
  $s = if (Test-Path $sf) { Get-Content $sf -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
  $e = if ($s.PSObject.Properties['env']) { $s.env } else { [pscustomobject]@{} }
  $e | Add-Member -Force -NotePropertyName HTTPS_PROXY -NotePropertyValue $Proxy
  $e | Add-Member -Force -NotePropertyName NO_PROXY -NotePropertyValue 'localhost,127.0.0.1'
  $s | Add-Member -Force -NotePropertyName env -NotePropertyValue $e
  [IO.File]::WriteAllText($sf, ($s | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
}
# Claude Code の installer は置き場（~\.local\bin）を PATH に足さず、足すよう案内だけ出すので、ここで足す
$bin = "$HOME\.local\bin"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $bin) {
  [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ";$bin"), 'User')
}
Refresh-Path
