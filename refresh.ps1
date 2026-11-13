# Zip Market Explorer - monthly refresh.
#   1. Download the five realtor.com Core Metrics *History* CSVs into raw\
#   2. Run:  .\refresh.ps1
# Builds site\d from raw\, verifies it, commits code changes to main, and publishes
# site\ to the gh-pages branch (replaced each time, so the repo never accumulates old data).
# Works in Windows PowerShell 5.1.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

# Pick up tools installed per-user (Python, Git, gh, Node) even in an old window.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

function Fail($msg) { Write-Host "`nREFRESH STOPPED: $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Git-Ok { & git @args; if ($LASTEXITCODE -ne 0) { Fail "git $($args -join ' ') failed" } }

foreach ($tool in 'python', 'git', 'gh') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Fail "$tool is not installed or not on PATH" }
}
& gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Fail "GitHub CLI is not logged in - run: gh auth login" }

# ---- 1. build + validation report (build.py exits non-zero on any failed check)
Step 'Building data from raw\'
& python build.py
if ($LASTEXITCODE -ne 0) { Fail 'build.py reported a problem (see FAIL lines above). Nothing was published.' }

# ---- 2. sanity checks on the output
Step 'Verifying output'
$metaPath = Join-Path $root 'site\d\meta.json'
if (-not (Test-Path $metaPath)) { Fail 'site\d\meta.json is missing' }
$meta = Get-Content $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
$latest = [string]$meta.months[-1]
$label = $latest.Substring(0, 4) + '-' + $latest.Substring(4, 2)
$zipShards = @(Get-ChildItem (Join-Path $root 'site\d\zip') -Filter *.json -ErrorAction SilentlyContinue).Count
if ($zipShards -lt 90) { Fail "only $zipShards zip shards were built (expected ~99)" }
if (-not $meta.hasUS) { Fail 'US data is missing - is RDC_Inventory_Core_Metrics_Country_History.csv in raw\?' }
$sizeMB = [math]::Round(((Get-ChildItem (Join-Path $root 'site') -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
if ($sizeMB -gt 900) { Fail "site\ is $sizeMB MB - too close to the 1 GB GitHub Pages limit" }
if (Get-Command node -ErrorAction SilentlyContinue) {
    $html = Get-Content (Join-Path $root 'site\index.html') -Raw -Encoding UTF8
    $m = [regex]::Match($html, '(?s)<script>(.*?)</script>')
    $tmp = Join-Path $env:TEMP 'zme-app-check.js'
    [IO.File]::WriteAllText($tmp, $m.Groups[1].Value)
    & node --check $tmp; $ok = ($LASTEXITCODE -eq 0); Remove-Item $tmp -ErrorAction SilentlyContinue
    if (-not $ok) { Fail 'node --check found a JavaScript syntax error in site\index.html' }
    & node --check (Join-Path $root 'site\sw.js'); if ($LASTEXITCODE -ne 0) { Fail 'node --check failed on site\sw.js' }
}
Write-Host "Latest month: $label   zip shards: $zipShards   site size: $sizeMB MB"
$msg = "Data refresh $label"

# ---- 3. commit code changes on main (data is not tracked on main)
Step 'Committing code to main'
Git-Ok add -A
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { Git-Ok commit -q -m $msg; Write-Host 'Committed.' } else { Write-Host 'No code changes.' }
Git-Ok push -q origin main

# ---- 4. publish site\ to gh-pages as a single fresh commit
Step 'Publishing site\ to GitHub Pages'
$remote = (& git remote get-url origin).Trim()
$name = (& git config user.name); $email = (& git config user.email)
$stage = Join-Path $env:TEMP ('zme-pages-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    Copy-Item (Join-Path $root 'site\*') $stage -Recurse
    New-Item -ItemType File -Path (Join-Path $stage '.nojekyll') | Out-Null
    Push-Location $stage
    Git-Ok init -q -b gh-pages
    Git-Ok config user.name $name
    Git-Ok config user.email $email
    Git-Ok add -A
    Git-Ok commit -q -m $msg
    Write-Host "Uploading about $sizeMB MB - this can take a few minutes..."
    Git-Ok push -q --force $remote gh-pages
    Pop-Location
} finally {
    if ((Get-Location).Path -eq $stage) { Pop-Location }
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}

$owner = (& gh repo view --json owner --jq .owner.login).Trim()
Write-Host "`nDone: $msg published. Live in a few minutes at https://$owner.github.io/zip-market-explorer/" -ForegroundColor Green
