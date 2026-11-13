param(
    [ValidateSet('install','upgrade','rollback','uninstall')][string]$Action = 'install',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\LazyToken'),
    [string]$Source = (Join-Path $PSScriptRoot 'LazyToken'),
    [switch]$ConfirmUninstall
)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($InstallRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$VolumeRoot = [IO.Path]::GetPathRoot($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
if (-not $Root -or $Root -eq $VolumeRoot) { throw 'Choose a dedicated application directory.' }
$Marker = Join-Path $Root '.lazytoken-install'
$Versions = Join-Path $Root 'versions'
$Current = Join-Path $Root 'current.txt'
$Previous = Join-Path $Root 'previous.txt'
$Launcher = Join-Path $Root 'LazyToken.cmd'
function Assert-Installation {
    $Item = Get-Item -LiteralPath $Root -Force
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or (Resolve-Path -LiteralPath $Root).Path -ne $Root) { throw 'Installation root must be a regular local directory.' }
    if (-not (Test-Path -LiteralPath $Marker -PathType Leaf) -or (Get-Content -Raw -LiteralPath $Marker).Trim() -ne 'LazyToken-managed-install-v1') { throw 'This is not a recognized LazyToken installation.' }
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
    $Lines = @('@echo off',('"%~dp0versions\'+$Version+'\LazyToken.exe" %*'))
    [IO.File]::WriteAllLines($Launcher,$Lines,[Text.Encoding]::ASCII)
    [IO.File]::WriteAllText($Current,$Version,[Text.Encoding]::ASCII)
}
if ($Action -in @('install','upgrade')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Source 'LazyToken.exe') -PathType Leaf)) { throw 'Source must be a built LazyToken distribution.' }
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
    if ($Old) { [IO.File]::WriteAllText($Previous,$Old,[Text.Encoding]::ASCII) }
    Set-Launcher $Version
    Write-Host "LazyToken installed at $Root. Run $Launcher dashboard"
} elseif ($Action -eq 'rollback') {
    Assert-Installation
    $Old = Read-Version $Current; $Version = Read-Version $Previous
    if (-not $Version) { throw 'No previous version is recorded.' }
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
        }
        foreach ($Item in (Get-ChildItem -LiteralPath $Versions -Force)) { Remove-Item -LiteralPath $Item.FullName -Recurse -Force }
        Remove-Item -LiteralPath $Versions -Force
    }
    foreach ($Path in @($Launcher,$Current,$Previous,$Marker)) { if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force } }
    if (-not (Get-ChildItem -LiteralPath $Root -Force)) { Remove-Item -LiteralPath $Root -Force }
    Write-Host 'LazyToken application files removed. The knowledge database was retained.'
}
