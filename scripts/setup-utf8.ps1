# ============================================================
# setup-utf8.ps1 — 永久设置 PowerShell 编码为 UTF-8
# 用法: .\scripts\setup-utf8.ps1
# ============================================================

$profilePath = $PROFILE.CurrentUserAllHosts
if (!(Test-Path $profilePath)) {
    New-Item -Force -Path $profilePath -ItemType File | Out-Null
    Write-Host "Created profile: $profilePath"
}

$utf8Config = @'

# UTF-8 encoding
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$PSDefaultParameterValues["*:Encoding"] = "utf8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
'@

Set-Content -Path $profilePath -Value $utf8Config -Encoding UTF8
Write-Host "UTF-8 config written to: $profilePath"
Write-Host "Restart your terminal to take effect."
