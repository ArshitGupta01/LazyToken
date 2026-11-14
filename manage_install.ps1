param(
    [ValidateSet('install','upgrade','rollback','uninstall')][string]$Action = 'install',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\LazyToken'),
    [string]$Source = (Join-Path $PSScriptRoot 'LazyToken'),
    [switch]$ConfirmUninstall,
    [switch]$RegisterPath,
    [string]$PathStateFile
)
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

$Root = [IO.Path]::GetFullPath($InstallRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$VolumeRoot = [IO.Path]::GetPathRoot($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
if (-not $Root -or $Root -eq $VolumeRoot) { throw 'Choose a dedicated application directory.' }
$Ancestor=Split-Path -Parent $Root
while ($Ancestor) {
    if ((Test-Path -LiteralPath $Ancestor) -and ((Get-Item -LiteralPath $Ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Installation parents must not be links or junctions.' }
    $Parent=Split-Path -Parent $Ancestor
    if ($Parent -eq $Ancestor) { break };$Ancestor=$Parent
}
$Marker = Join-Path $Root '.lazytoken-install'
$Versions = Join-Path $Root 'versions'
$Current = Join-Path $Root 'current.txt'
$Previous = Join-Path $Root 'previous.txt'
$Launcher = Join-Path $Root 'LazyToken.cmd'
$Bin = Join-Path $Root 'bin'
$PathReceipt = Join-Path $Root '.path-registration.json'
function Read-UserPath {
    if ($PathStateFile) { if (Test-Path -LiteralPath $PathStateFile) { return [IO.File]::ReadAllText($PathStateFile) }; return '' }
    return [Environment]::GetEnvironmentVariable('Path','User')
}
function Write-UserPath([string]$Value) {
    if ($PathStateFile) { [IO.File]::WriteAllText($PathStateFile,$Value) } else { [Environment]::SetEnvironmentVariable('Path',$Value,'User') }
}
function Register-UserPath {
    if (Test-Path -LiteralPath $PathReceipt) { return }
    $Before = [string](Read-UserPath)
    $Present = @($Before.Split(';') | Where-Object { $_.TrimEnd('\') -ieq $Bin.TrimEnd('\') }).Count -gt 0
    $After=$Before
    if (-not $Present) { $Separator=if ($Before -and -not $Before.EndsWith(';')) {';'} else {''};$After=$Before+$Separator+$Bin;Write-UserPath $After }
    @{bin=$Bin;owned=(-not $Present);pathStateFile=$PathStateFile;before=$Before;after=$After} | ConvertTo-Json | Set-Content -LiteralPath $PathReceipt -Encoding UTF8
}
function Remove-UserPath {
    if (-not (Test-Path -LiteralPath $PathReceipt)) { return }
    $Receipt = Get-Content -Raw -LiteralPath $PathReceipt | ConvertFrom-Json
    if ($Receipt.bin -ne $Bin) { throw 'Unexpected PATH ownership record.' }
    if ($Receipt.pathStateFile) { $script:PathStateFile = $Receipt.pathStateFile }
    if ($Receipt.owned) {
        $CurrentPath=[string](Read-UserPath)
        if ($null -ne $Receipt.before -and $CurrentPath -ceq $Receipt.after) { Write-UserPath $Receipt.before }
        else { Write-UserPath (($CurrentPath.Split(';') | Where-Object { $_.TrimEnd('\') -ine $Bin.TrimEnd('\') }) -join ';') }
    }
}
function Assert-Installation {
    $Item = Get-Item -LiteralPath $Root -Force
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or (Resolve-Path -LiteralPath $Root).Path -ne $Root) { throw 'Installation root must be a regular local directory.' }
    if (-not (Test-Path -LiteralPath $Marker -PathType Leaf) -or (Get-Content -Raw -LiteralPath $Marker).Trim() -ne 'LazyToken-managed-install-v1') { throw 'This is not a recognized LazyToken installation.' }
    foreach ($Managed in @($Versions,$Bin,$Launcher,$Current,$Previous,$PathReceipt)) { if ((Test-Path -LiteralPath $Managed) -and ((Get-Item -LiteralPath $Managed -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Managed installation paths cannot be links or junctions.' } }
}
function Verify-Package([string]$Directory) {
    $ManifestPath=Join-Path $Directory 'release-manifest.json'
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw 'Package integrity manifest is missing.' }
    $Manifest=Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
    if ($Manifest.format -ne 'lazytoken-files-v1' -or -not $Manifest.files.'LazyToken.exe') { throw 'Invalid package manifest.' }
    $Base=[IO.Path]::GetFullPath($Directory).TrimEnd('\')
    foreach ($File in (Get-ChildItem -LiteralPath $Directory -Recurse -File -Force)) {
        $Relative=$File.FullName.Substring($Base.Length+1).Replace('\','/')
        if ($Relative -eq 'release-manifest.json') { continue }
        $Expected=$Manifest.files.PSObject.Properties[$Relative]
        if (-not $Expected -or $Expected.Value -notmatch '^[a-fA-F0-9]{64}$' -or (Get-Sha256 $File.FullName) -ne $Expected.Value) { throw "Package integrity failed: $Relative" }
    }
    foreach ($Property in $Manifest.files.PSObject.Properties) {
        if ($Property.Name.Contains(':') -or $Property.Name.StartsWith('/') -or $Property.Name.Split('/') -contains '..') { throw 'Unsafe manifest path.' }
        $Target=[IO.Path]::GetFullPath((Join-Path $Base $Property.Name))
        if (-not $Target.StartsWith($Base+'\',[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $Target -PathType Leaf)) { throw 'Manifest references missing or unsafe files.' }
    }
}
function Write-AtomicText([string]$Path,[string]$Value) {
    $Temporary=$Path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    [IO.File]::WriteAllText($Temporary,$Value,[Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $Path) { $Backup=$Path+'.atomic-backup';[IO.File]::Replace($Temporary,$Path,$Backup);[IO.File]::Delete($Backup) } else { [IO.File]::Move($Temporary,$Path) }
}
function Read-Version([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $Value = (Get-Content -Raw -LiteralPath $Path).Trim()
    if ($Value -notmatch '^[a-f0-9]{32}$') { throw 'The installation version marker is invalid.' }
    return $Value
}
function Set-Launcher([string]$Version) {
    $Exe = Join-Path (Join-Path $Versions $Version) 'LazyToken.exe'
    if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw 'The selected version is incomplete.' }
    $Lines = @('@echo off','"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0dispatch.ps1" %*')
    [IO.File]::WriteAllLines($Launcher,$Lines,[Text.Encoding]::ASCII)
    New-Item -ItemType Directory -Force -Path $Bin | Out-Null
    [IO.File]::WriteAllLines((Join-Path $Bin 'lazytoken.cmd'),@('@echo off','"%~dp0..\LazyToken.cmd" %*'),[Text.Encoding]::ASCII)
    Write-AtomicText $Current $Version
}
if ($Action -in @('install','upgrade')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Source 'LazyToken.exe') -PathType Leaf)) { throw 'Source must be a built LazyToken distribution.' }
    foreach ($Item in @(Get-Item -LiteralPath $Source) + @(Get-ChildItem -LiteralPath $Source -Recurse -Force)) { if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Package directories must not contain links or junctions.' } }
    Verify-Package $Source
    if (Test-Path -LiteralPath $Root) { Assert-Installation } else {
        New-Item -ItemType Directory -Path $Root | Out-Null
        [IO.File]::WriteAllText($Marker,'LazyToken-managed-install-v1',[Text.Encoding]::ASCII)
    }
    New-Item -ItemType Directory -Force -Path $Versions | Out-Null
    $Old = Read-Version $Current
    $Version = [guid]::NewGuid().ToString('N')
    $Target = Join-Path $Versions $Version
    New-Item -ItemType Directory -Path $Target | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Target -Recurse -Force
    if (-not (Test-Path -LiteralPath (Join-Path $Target 'LazyToken.exe') -PathType Leaf)) { throw 'Copy failed; existing version remains selected.' }
    Verify-Package $Target
    if ($Old) { [IO.File]::WriteAllText($Previous,$Old,[Text.Encoding]::ASCII) }
    $Support = Join-Path $Source '_internal\distribution'
    if (Test-Path -LiteralPath $Support) {
        foreach ($Name in @('dispatch.ps1','manage_install.ps1','install.ps1')) { Copy-Item -LiteralPath (Join-Path $Support $Name) -Destination (Join-Path $Root $Name) -Force }
    } elseif (-not (Test-Path -LiteralPath (Join-Path $Root 'dispatch.ps1'))) {
        # Unit fixtures and older local packages retain their direct executable launcher.
        [IO.File]::WriteAllLines((Join-Path $Root 'dispatch.ps1'),@('param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CliArgs)','$v=(Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "current.txt")).Trim()','& (Join-Path $PSScriptRoot ("versions\"+$v+"\LazyToken.exe")) @CliArgs','exit $LASTEXITCODE'),[Text.Encoding]::UTF8)
    }
    Set-Launcher $Version
    if ($RegisterPath) { Register-UserPath }
    Write-Host "LazyToken installed at $Root. Run $Launcher dashboard"
} elseif ($Action -eq 'rollback') {
    Assert-Installation
    $Old = Read-Version $Current; $Version = Read-Version $Previous
    if (-not $Version) { throw 'No previous version is recorded.' }
    Verify-Package (Join-Path $Versions $Version)
    Set-Launcher $Version
    if ($Old) { [IO.File]::WriteAllText($Previous,$Old,[Text.Encoding]::ASCII) }
    Write-Host 'LazyToken rolled back to the previous installed version.'
} else {
    Assert-Installation
    if (-not $ConfirmUninstall) { throw 'Use -ConfirmUninstall to remove the installed application files. The knowledge database is retained.' }
    # Resolve each managed target before recursive deletion; refuse reparse points and unexpected names.
    if (Test-Path -LiteralPath $Versions) {
        $ResolvedVersions=(Resolve-Path -LiteralPath $Versions).Path
        $ExpectedVersions=[IO.Path]::GetFullPath($Versions)
        if ($ResolvedVersions -ne $ExpectedVersions -or (Get-Item -LiteralPath $Versions -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected versions directory; uninstall stopped.' }
        foreach ($Item in (Get-ChildItem -LiteralPath $Versions -Force)) {
            if (-not $Item.PSIsContainer -or $Item.Name -notmatch '^[a-f0-9]{32}$' -or ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unexpected item in versions; uninstall stopped.' }
            $Resolved=(Resolve-Path -LiteralPath $Item.FullName).Path
            if (-not $Resolved.StartsWith($ResolvedVersions+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Version path leaves installation directory.' }
            foreach ($Nested in (Get-ChildItem -LiteralPath $Item.FullName -Recurse -Force)) { if ($Nested.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Version contains a link or junction; uninstall stopped.' } }
        }
        foreach ($Item in (Get-ChildItem -LiteralPath $Versions -Force)) { Remove-Item -LiteralPath $Item.FullName -Recurse -Force }
        Remove-Item -LiteralPath $Versions -Force
    }
    Remove-UserPath
    $BinLauncher = Join-Path $Bin 'lazytoken.cmd'
    if (Test-Path -LiteralPath $BinLauncher) { Remove-Item -LiteralPath $BinLauncher -Force }
    if ((Test-Path -LiteralPath $Bin) -and -not (Get-ChildItem -LiteralPath $Bin -Force)) { Remove-Item -LiteralPath $Bin -Force }
    foreach ($Path in @($Launcher,$Current,$Previous,$Marker,$PathReceipt,(Join-Path $Root '.publisher.json'),(Join-Path $Root 'dispatch.ps1'),(Join-Path $Root 'manage_install.ps1'),(Join-Path $Root 'install.ps1'))) { if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force } }
    if (-not (Get-ChildItem -LiteralPath $Root -Force)) { Remove-Item -LiteralPath $Root -Force }
    Write-Host 'LazyToken application files removed. The knowledge database was retained.'
}
