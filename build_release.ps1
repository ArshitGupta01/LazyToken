param([string]$Output = (Join-Path $PSScriptRoot 'release'))
$ErrorActionPreference = 'Stop'
$Python = (Get-Command python -ErrorAction Stop).Source
& $Python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Install the build-only dependency PyInstaller 6.19.0 first.' }
$Version = (& $Python -m PyInstaller --version).Trim()
if ($Version -ne '6.19.0') { throw "Expected PyInstaller 6.19.0; found $Version" }
$Output = [System.IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath (Join-Path $Output 'LazyToken')) { throw 'Output already exists. Select a new -Output directory to preserve the previous build.' }
if (Test-Path -LiteralPath (Join-Path $Output 'install.ps1')) { throw 'Output installer already exists. Select a new -Output directory.' }
$Assets = @('index.html','styles.css','app.js','features-ui.js','graph3d.js','POLICY.md','task.md','README.md','IMPLEMENTATION_STATUS.md','THIRD_PARTY_NOTICES.md','LICENSE')
$PyArgs = @('--noconfirm','--onedir','--name','LazyToken','--distpath',$Output,'--workpath',(Join-Path $PSScriptRoot 'build\pyinstaller'),'--specpath',(Join-Path $PSScriptRoot 'build'))
foreach ($Asset in $Assets) {
    $PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot $Asset);.")
}
$PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot 'benchmark\corpus.json');benchmark")
foreach ($Asset in @('three.module.js','three.core.js','OrbitControls.js','THREE-LICENSE.txt')) { $PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot ('vendor\'+$Asset));vendor") }
foreach ($Asset in @('README.md','notebook.py','test_notebook.py')) { $PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot ('benchmark\fixture_notebook\'+$Asset));benchmark\fixture_notebook") }
$PyArgs += (Join-Path $PSScriptRoot 'app_entry.py')
& $Python -m PyInstaller @PyArgs
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'manage_install.ps1') -Destination (Join-Path $Output 'install.ps1')
Write-Host "Built $Output\LazyToken\LazyToken.exe"
