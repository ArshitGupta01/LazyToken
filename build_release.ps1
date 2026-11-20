param([string]$Output = (Join-Path $PSScriptRoot 'release'))
$ErrorActionPreference = 'Stop'
function Get-Sha256([string]$Path) {
    # Keep bootstrap hashing independent of optional PowerShell modules.
    $Stream = [IO.File]::OpenRead($Path)
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($Hasher.ComputeHash($Stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $Stream.Dispose()
        $Hasher.Dispose()
    }
}

$Python = (Get-Command python -ErrorAction Stop).Source
& $Python -c "import sys, sysconfig; sys.exit(0 if sys.version_info[:2] == (3, 14) and sys.version_info[:3] >= (3, 14, 10) and sysconfig.get_platform() == 'win-amd64' else 1)"
if ($LASTEXITCODE -ne 0) { throw 'The Windows x64 release requires 64-bit Windows Python 3.14.10 or newer in the 3.14 series.' }
& $Python -c "import ssl, sys; v=ssl.OPENSSL_VERSION_INFO; sys.exit(0 if v[:2] == (3, 5) and v[3] >= 9 else 1)"
if ($LASTEXITCODE -ne 0) { throw 'The release requires OpenSSL 3.5.9 or newer in the supported 3.5 LTS series; upgrade Python before building.' }
$PythonLicense = (& $Python -c "import pathlib, sys; print(pathlib.Path(sys.base_prefix) / 'LICENSE.txt')").Trim()
if (-not (Test-Path -LiteralPath $PythonLicense -PathType Leaf)) { throw 'Python license is missing; use a Python installation with its license notice.' }
& $Python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Install the build-only dependency PyInstaller 6.19.0 first.' }
$Version = (& $Python -m PyInstaller --version).Trim()
if ($Version -ne '6.19.0') { throw "Expected PyInstaller 6.19.0; found $Version" }
$TokenizerVersion = (& $Python -c "from importlib.metadata import version; print(version('tokenizers'))").Trim()
if ($LASTEXITCODE -ne 0 -or $TokenizerVersion -ne '0.23.3') { throw 'This build requires tokenizers==0.23.3 to match the bundled license and tested adapter.' }
$Output = [System.IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath (Join-Path $Output 'TokSmart')) { throw 'Output already exists. Select a new -Output directory to preserve the previous build.' }
if (Test-Path -LiteralPath (Join-Path $Output 'install.ps1')) { throw 'Output installer already exists. Select a new -Output directory.' }
$Assets = @('index.html','styles.css','logo.svg','app.js','features-ui.js','graph3d.js','POLICY.md','README.md','THIRD_PARTY_NOTICES.md','RELEASING.md','LICENSE')
$PyArgs = @('--noconfirm','--onedir','--name','TokSmart','--distpath',$Output,'--workpath',(Join-Path $PSScriptRoot 'build\pyinstaller'),'--specpath',(Join-Path $PSScriptRoot 'build'))
foreach ($Asset in $Assets) {
    $PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot $Asset);.")
}
$PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot 'benchmark\corpus.json');benchmark")
$PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot 'web\prompts.json');web")
foreach ($Doc in @('CLI.md','CLIENT_COMPATIBILITY.md')) { $PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot ('docs\'+$Doc));docs") }
$PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot 'web/theme.js');web")
foreach ($Asset in @('three.module.js','three.core.js','OrbitControls.js','THREE-LICENSE.txt','TOKENIZERS-LICENSE.txt')) { $PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot ('vendor\'+$Asset));vendor") }
foreach ($Asset in @('README.md','notebook.py','test_notebook.py')) { $PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot ('benchmark\fixture_notebook\'+$Asset));benchmark\fixture_notebook") }
foreach ($Support in @('install.ps1','manage_install.ps1','dispatch.ps1')) { $PyArgs += @('--add-data',"$(Join-Path $PSScriptRoot $Support);distribution") }
$PyArgs += (Join-Path $PSScriptRoot 'app_entry.py')
& $Python -m PyInstaller @PyArgs
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
Copy-Item -LiteralPath $PythonLicense -Destination (Join-Path $Output 'TokSmart\_internal\vendor\PYTHON-LICENSE.txt')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'manage_install.ps1') -Destination (Join-Path $Output 'install.ps1')
Write-Host "Built $Output\TokSmart\TokSmart.exe"

# Hash every file in the onedir package, then produce a versioned zip and checksums.
$PackageRoot = Join-Path $Output 'TokSmart'
$Manifest = [ordered]@{format='toksmart-files-v1';files=[ordered]@{}}
foreach ($File in (Get-ChildItem -LiteralPath $PackageRoot -Recurse -File | Sort-Object FullName)) {
    $Relative = $File.FullName.Substring($PackageRoot.Length+1).Replace('\','/')
    $Manifest.files[$Relative] = (Get-Sha256 $File.FullName).ToLowerInvariant()
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $PackageRoot 'release-manifest.json') -Encoding UTF8
$AppVersion = (& $Python -c "import sys; sys.path.insert(0, sys.argv[1]); import kn; print(kn.VERSION)" $PSScriptRoot).Trim()
$ZipName = 'toksmart-v'+$AppVersion+'-windows-x64.zip'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Staging = Join-Path $Output 'archive-stage'
New-Item -ItemType Directory -Path $Staging | Out-Null
Copy-Item -LiteralPath $PackageRoot -Destination (Join-Path $Staging 'TokSmart') -Recurse
Copy-Item -LiteralPath (Join-Path $Output 'install.ps1') -Destination (Join-Path $Staging 'install.ps1')
[IO.Compression.ZipFile]::CreateFromDirectory($Staging,(Join-Path $Output $ZipName))
$Hash = (Get-Sha256 (Join-Path $Output $ZipName)).ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $Output 'SHA256SUMS'),($Hash+'  '+$ZipName+"`n"),[Text.Encoding]::ASCII)
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install.ps1') -Destination (Join-Path $Output 'bootstrap.ps1')
Write-Host "Release archive: $Output\$ZipName"
$BootstrapHash = (Get-Sha256 (Join-Path $Output 'bootstrap.ps1')).ToLowerInvariant()
[IO.File]::AppendAllText((Join-Path $Output 'SHA256SUMS'),($BootstrapHash+"  bootstrap.ps1`n"),[Text.Encoding]::ASCII)
