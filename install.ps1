param([string]$Version='latest',[string]$InstallRoot=(Join-Path $env:LOCALAPPDATA 'Programs\LazyToken'),[string]$PackagePath,[string]$ExpectedSha256,[string]$PublisherThumbprint,[switch]$Upgrade,[switch]$NoPathRegistration)
$ErrorActionPreference='Stop'
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

$ProgressPreference='SilentlyContinue'
$PublisherRecord=Join-Path $InstallRoot '.publisher.json'
if (Test-Path -LiteralPath $PublisherRecord) {
    $Pinned=(Get-Content -Raw -LiteralPath $PublisherRecord | ConvertFrom-Json).thumbprint
    if ($PublisherThumbprint -and $Pinned -ne $PublisherThumbprint) {throw 'Publisher differs from the existing installation pin.'}
    $PublisherThumbprint=$Pinned
}
if ($PublisherThumbprint -and $PublisherThumbprint -notmatch '^[a-fA-F0-9]{40}$') {throw 'Invalid trusted publisher certificate thumbprint.'}
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
$Architecture=if ($env:PROCESSOR_ARCHITEW6432) {$env:PROCESSOR_ARCHITEW6432} else {$env:PROCESSOR_ARCHITECTURE}
if ($Architecture -ne 'AMD64') { throw 'No verified package for this Windows architecture.' }
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$TempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$Stage=Join-Path $TempRoot ('LazyToken-install-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Stage | Out-Null
try {
    if (-not $PackagePath) {
        if ($Version -ne 'latest' -and $Version -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?$') { throw 'Invalid version tag.' }
        $Api=if ($Version -eq 'latest') {'https://api.github.com/repos/ArshitGupta01/LazyToken/releases/latest'} else {'https://api.github.com/repos/ArshitGupta01/LazyToken/releases/tags/'+$Version}
        try {$Release=Invoke-RestMethod -Uri $Api -Headers @{Accept='application/vnd.github+json';'User-Agent'='LazyToken-installer'}} catch {throw 'No accessible verified release. Nothing installed. Publication of a tested release is required.'}
        if ($Release.draft -or $Release.tag_name -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?$') {throw 'Unsupported release metadata.'}
        $Name='lazytoken-'+$Release.tag_name+'-windows-x64.zip'
        $Assets=@($Release.assets | Where-Object {$_.name -eq $Name})
        if ($Assets.Count -ne 1) {throw "Missing unique artifact: $Name"}
        $Asset=$Assets[0]
        if ($Asset.digest -notmatch '^sha256:([a-fA-F0-9]{64})$') {throw 'Release lacks a trusted SHA-256 digest; refused.'}
        $PublishedHash=$Matches[1]
        if ($ExpectedSha256 -and $ExpectedSha256 -ne $PublishedHash) {throw 'Independent checksum differs from release metadata.'}
        $ExpectedSha256=$PublishedHash
        if ($Asset.size -le 0 -or $Asset.size -gt 268435456) {throw 'Unsupported artifact size.'}
        $Prefix='https://github.com/ArshitGupta01/LazyToken/releases/download/'+$Release.tag_name+'/'
        if (-not $Asset.browser_download_url.StartsWith($Prefix,[StringComparison]::Ordinal)) {throw 'Unexpected download location.'}
        $PackagePath=Join-Path $Stage $Name
        Invoke-WebRequest -UseBasicParsing -Uri $Asset.browser_download_url -OutFile $PackagePath
    }
    if ($ExpectedSha256 -notmatch '^[a-fA-F0-9]{64}$') {throw 'A trusted SHA-256 is mandatory.'}
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf) -or (Get-Item -LiteralPath $PackagePath).Length -gt 268435456) {throw 'Artifact missing or too large.'}
    if ((Get-Sha256 $PackagePath) -ne $ExpectedSha256) {throw 'SHA-256 mismatch. No downloaded code was executed.'}
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive=[IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($PackagePath))
    $Extract=Join-Path $Stage 'verified'
    New-Item -ItemType Directory -Path $Extract | Out-Null
    try {
        $Seen=@{};[long]$Total=0
        if ($Archive.Entries.Count -gt 5000) {throw 'Too many archive entries.'}
        foreach ($Entry in $Archive.Entries) {
            $Name=$Entry.FullName.Replace('\','/');$Parts=$Name.Split('/')
            if ($Name.StartsWith('/') -or $Name.Contains(':') -or $Parts -contains '..' -or $Parts -contains '.' -or (($Entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) {throw 'Unsafe archive path or symlink.'}
            foreach ($Part in $Parts) {if ($Part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)' -or $Part.EndsWith('.') -or $Part.EndsWith(' ')) {throw 'Unsupported Windows archive name.'}}
            if ($Seen.ContainsKey($Name.ToLowerInvariant())) {throw 'Duplicate archive entry.'};$Seen[$Name.ToLowerInvariant()]=$true
            $Total+=$Entry.Length
            if ($Total -gt 1073741824 -or $Entry.Length -gt 134217728) {throw 'Expanded archive exceeds limits.'}
            $Target=[IO.Path]::GetFullPath((Join-Path $Extract $Name))
            if (-not $Target.StartsWith($Extract+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {throw 'Archive leaves extraction root.'}
        }
        foreach ($Entry in $Archive.Entries) {
            $Target=[IO.Path]::GetFullPath((Join-Path $Extract $Entry.FullName))
            if ($Entry.FullName.EndsWith('/')) {New-Item -ItemType Directory -Force -Path $Target | Out-Null} else {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry,$Target,$false)
            }
        }
    } finally {$Archive.Dispose()}
    foreach ($Required in @('install.ps1','LazyToken\release-manifest.json','LazyToken\LazyToken.exe','LazyToken\_internal\python311.dll','LazyToken\_internal\index.html','LazyToken\_internal\vendor\three.module.js')) {if (-not (Test-Path -LiteralPath (Join-Path $Extract $Required) -PathType Leaf)) {throw "Incomplete artifact: $Required"}}
    if ($PublisherThumbprint) {
        if (-not (Get-Command Get-AuthenticodeSignature -ErrorAction SilentlyContinue)) {throw 'Authenticode verification unavailable; refusing the publisher-pinned install.'}
        foreach ($SignedFile in @('install.ps1','LazyToken\LazyToken.exe')) {
            $Signature=Get-AuthenticodeSignature -LiteralPath (Join-Path $Extract $SignedFile)
            if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Thumbprint -ne $PublisherThumbprint) {throw 'Trusted publisher signature verification failed.'}
        }
    }
    $Options=@{Action=$(if ($Upgrade) {'upgrade'} else {'install'});InstallRoot=$InstallRoot;Source=(Join-Path $Extract 'LazyToken')}
    $PreviouslyRegistered=Test-Path -LiteralPath (Join-Path $InstallRoot '.path-registration.json')
    if (-not $NoPathRegistration -and (-not $Upgrade -or $PreviouslyRegistered)) {$Options.RegisterPath=$true}
    & (Join-Path $Extract 'install.ps1') @Options
    if (-not $?) {throw 'Managed install failed; prior version retained.'}
    if ($PublisherThumbprint) {@{thumbprint=$PublisherThumbprint} | ConvertTo-Json | Set-Content -LiteralPath $PublisherRecord -Encoding UTF8}
    Write-Host 'Open a new terminal. Run lazytoken init, then lazytoken add <repository>.'
} finally {
    $Resolved=[IO.Path]::GetFullPath($Stage)
    if ($Resolved.StartsWith($TempRoot,[StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $Resolved) -match '^LazyToken-install-[a-f0-9]{32}$' -and (Test-Path -LiteralPath $Resolved) -and -not ((Get-Item -LiteralPath $Resolved).Attributes -band [IO.FileAttributes]::ReparsePoint)) {Remove-Item -LiteralPath $Resolved -Recurse -Force}
}
