param(
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputRoot) { $OutputRoot = Join-Path $RepoRoot "artifacts" }
$BundleRoot = Join-Path $OutputRoot "AlinCode"
$Archive = Join-Path $OutputRoot "AlinCode-windows-x64.zip"
$BuildRoot = Join-Path $RepoRoot "build\pyinstaller"

if (Test-Path -LiteralPath $BundleRoot) { throw "输出目录已存在：$BundleRoot" }
if (Test-Path -LiteralPath $Archive) { throw "输出压缩包已存在：$Archive" }
New-Item -ItemType Directory -Force $OutputRoot | Out-Null

Push-Location (Join-Path $RepoRoot "webui")
try {
    npm ci
    npm run build
} finally {
    Pop-Location
}

uv run pyinstaller --onedir --name AlinCode --noconfirm `
    --distpath $OutputRoot --workpath $BuildRoot --specpath $BuildRoot `
    --add-data "$RepoRoot\webui\dist;webui\dist" `
    --collect-all webview --collect-all Alincode.subagent.builtin `
    "$RepoRoot\Alincode\__main__.py"

Compress-Archive -Path (Join-Path $BundleRoot "*") -DestinationPath $Archive
Write-Host "已生成：$Archive"
