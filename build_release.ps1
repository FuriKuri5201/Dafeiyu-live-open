# Build a standalone Win64 portable package (no Python installation required on target PC).
# Output: dist\DFYZB-Open-Win64-Portable.zip (ready for GitHub Releases)
# Optional: compile installer.iss with Inno Setup to produce DFYZB-OneClick-Setup.exe

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PyVer = "3.13.3"
$PyMajorMinor = "313"
$EmbedZip = Join-Path $Root "build\python-$PyVer-embed-amd64.zip"
$StageDir = Join-Path $Root "dist\DFYZB-Open"
$RuntimeDir = Join-Path $StageDir "runtime"
$SitePackages = Join-Path $RuntimeDir "Lib\site-packages"
$OutZip = Join-Path $Root "dist\DFYZB-Open-Win64-Portable.zip"

New-Item -ItemType Directory -Force -Path (Join-Path $Root "build"), (Join-Path $Root "dist") | Out-Null

# 1. Download official Windows 64-bit Python Embeddable Package
if (-not (Test-Path $EmbedZip)) {
    $Urls = @(
        "https://mirrors.huaweicloud.com/python/$PyVer/python-$PyVer-embed-amd64.zip",
        "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip"
    )
    $Downloaded = $false
    foreach ($u in $Urls) {
        try {
            Write-Host "[1/5] Downloading Python $PyVer embeddable from $u ..."
            Invoke-WebRequest -Uri $u -OutFile $EmbedZip -UseBasicParsing
            $Downloaded = $true
            break
        } catch {
            Write-Warning "Download failed from $u : $_"
        }
    }
    if (-not $Downloaded) {
        throw "Could not download python-$PyVer-embed-amd64.zip. Place it manually in build\ and retry."
    }
}

# 2. Prepare clean staging directory
Write-Host "[2/5] Preparing $StageDir ..."
if (Test-Path $StageDir) { Remove-Item -Recurse -Force $StageDir }
New-Item -ItemType Directory -Force -Path $RuntimeDir, $SitePackages, (Join-Path $StageDir "music") | Out-Null

Expand-Archive -Path $EmbedZip -DestinationPath $RuntimeDir -Force

# Enable site-packages & parent project root in ._pth
$PthFile = Join-Path $RuntimeDir "python$PyMajorMinor._pth"
$PthContent = @(
    "python$PyMajorMinor.zip"
    "."
    ".."
    "Lib\site-packages"
    "import site"
) -join "`r`n"
[System.IO.File]::WriteAllText($PthFile, $PthContent + "`r`n", [System.Text.Encoding]::ASCII)

# 3. Install dependencies into embedded runtime
Write-Host "[3/5] Installing Python dependencies into portable runtime ..."
$PipExe = Join-Path $Root ".venv\Scripts\pip.exe"
if (-not (Test-Path $PipExe)) {
    throw "Local .venv not found. Run start.bat once before building a release."
}
& $PipExe install -r requirements.txt --target $SitePackages --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple
if ($LASTEXITCODE -ne 0) {
    & $PipExe install -r requirements.txt --target $SitePackages --upgrade
    if ($LASTEXITCODE -ne 0) { throw "pip install into portable runtime failed." }
}

# Clean __pycache__ inside site-packages to reduce zip size
Get-ChildItem -Path $SitePackages -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 4. Copy clean project files (zero personal data / config.json / logs)
Write-Host "[4/5] Copying clean project files ..."
foreach ($f in @("app.py", "run_headless.py", "config.example.json", "LICENSE", "README.md", "requirements.txt")) {
    Copy-Item (Join-Path $Root $f) (Join-Path $StageDir $f) -Force
}
foreach ($d in @("core", "ui", "stage")) {
    Copy-Item (Join-Path $Root $d) (Join-Path $StageDir $d) -Recurse -Force
    Get-ChildItem -Path (Join-Path $StageDir $d) -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
Copy-Item (Join-Path $Root "music\README.txt") (Join-Path $StageDir "music\README.txt") -Force

# Write portable one-click launcher (ASCII + CRLF)
$LauncherBat = @(
    '@echo off'
    'cd /d "%~dp0"'
    'start "" "runtime\pythonw.exe" app.py'
    'exit /b 0'
) -join "`r`n"
[System.IO.File]::WriteAllText((Join-Path $StageDir "一键启动.bat"), $LauncherBat + "`r`n", [System.Text.Encoding]::ASCII)

# 5. Compress portable zip
Write-Host "[5/5] Creating $OutZip ..."
if (Test-Path $OutZip) { Remove-Item -Force $OutZip }
Compress-Archive -Path "$StageDir\*" -DestinationPath $OutZip -CompressionLevel Optimal

$SizeMB = [math]::Round((Get-Item $OutZip).Length / 1MB, 1)
Write-Host ""
Write-Host "BUILD SUCCESS: $OutZip ($SizeMB MB)" -ForegroundColor Green
Write-Host "Upload this zip to GitHub Releases. Users unzip and double-click 一键启动.bat (no Python needed)."
