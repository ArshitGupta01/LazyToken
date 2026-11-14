param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CliArgs)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $Root '.lazytoken-install'))) {
    throw 'Unrecognized LazyToken installation.'
}
function Get-CurrentExecutable {
    $Version = (Get-Content -Raw -LiteralPath (Join-Path $Root 'current.txt')).Trim()
    if ($Version -notmatch '^[a-f0-9]{32}$') { throw 'Invalid installed version marker.' }
    return Join-Path $Root ('versions\' + $Version + '\LazyToken.exe')
}
$Exe = Get-CurrentExecutable
$RestartWatch = $false
if (-not $CliArgs -or $CliArgs.Count -eq 0) { $CliArgs = @('--help') }

function Stop-BackgroundWatch {
    $HelpText = (& $Exe --help | Out-String)
    if ($HelpText -notmatch '\bwatch\b') { return }
    $State = (& $Exe watch status | Out-String) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect automatic sync before maintenance.' }
    $script:RestartWatch = [bool]$State.running
    & $Exe watch stop | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Stop the active watcher before lifecycle maintenance.' }
}
function Resume-BackgroundWatch {
    if (-not $RestartWatch -or $env:LAZYTOKEN_DISABLE_AUTOWATCH -eq '1') { return }
    $ActiveExe = Get-CurrentExecutable
    # Older compatible versions may predate automatic sync.
    if ((& $ActiveExe --help | Out-String) -match '\bwatch\b') {
        & $ActiveExe watch start
        if ($LASTEXITCODE -ne 0) { throw 'Application selected, but automatic sync could not restart. Run lazytoken watch start.' }
    }
}

switch ($CliArgs[0]) {
    'update' {
        $Options = @{ InstallRoot = $Root; Upgrade = $true }
        for ($i = 1; $i -lt $CliArgs.Count; $i++) {
            $Flag = $CliArgs[$i]
            if ($Flag -notin @('--version', '--package', '--sha256') -or $i + 1 -ge $CliArgs.Count) {
                throw 'Usage: lazytoken update [--version vX.Y.Z] [--package file.zip --sha256 HASH]'
            }
            $i++
            $Key = @{ '--version' = 'Version'; '--package' = 'PackagePath'; '--sha256' = 'ExpectedSha256' }[$Flag]
            $Options[$Key] = $CliArgs[$i]
        }
        Stop-BackgroundWatch
        try { & (Join-Path $Root 'install.ps1') @Options }
        finally { Resume-BackgroundWatch }
    }
    'rollback' {
        if ($CliArgs.Count -ne 1) { throw 'Usage: lazytoken rollback' }
        Stop-BackgroundWatch
        try { & (Join-Path $Root 'manage_install.ps1') -Action rollback -InstallRoot $Root }
        finally { Resume-BackgroundWatch }
    }
    'uninstall' {
        foreach ($Flag in @($CliArgs | Select-Object -Skip 1)) {
            if ($Flag -notin @('--yes', '--remove-clients')) {
                throw 'Usage: lazytoken uninstall --yes [--remove-clients]'
            }
        }
        if ($CliArgs -notcontains '--yes') {
            throw 'Run lazytoken uninstall --yes to remove managed application files. Knowledge data is preserved.'
        }
        Stop-BackgroundWatch
        try {
            if ($CliArgs -contains '--remove-clients') {
                & $Exe clients-remove --install-root $Root
                if ($LASTEXITCODE -ne 0) { throw 'Client removal refused; app files preserved.' }
            }
            & (Join-Path $Root 'manage_install.ps1') -Action uninstall -InstallRoot $Root -ConfirmUninstall
        } catch {
            Resume-BackgroundWatch
            throw
        }
    }
    default {
        & $Exe @CliArgs
        exit $LASTEXITCODE
    }
}
if (-not $?) { exit 1 }
