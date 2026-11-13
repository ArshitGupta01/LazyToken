param(
    [string]$ProjectRoot = $PSScriptRoot,
    [switch]$ConfigureClients,
    [switch]$InstallCodeGraphRag
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { throw 'Python is not on PATH. Install Python 3.11 or newer, then reopen PowerShell.' }
$Version = & $Python.Source -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
if ($LASTEXITCODE -ne 0 -or [version]$Version -lt [version]'3.11') { throw "Python 3.11+ required; found $Version" }
$DataRoot = if ($env:KN_HOME) { $env:KN_HOME } else { Join-Path $env:LOCALAPPDATA 'TheekHai\KnowledgeNetwork' }
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
$env:KN_HOME = $DataRoot
& $Python.Source (Join-Path $PSScriptRoot 'kn.py') sync $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Initial project indexing failed.' }
& $Python.Source (Join-Path $PSScriptRoot 'kn.py') seed $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Initial reusable asset graph setup failed.' }
& $Python.Source -m unittest discover -s (Join-Path $PSScriptRoot 'tests') -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Knowledge Network self-checks failed.' }

if ($InstallCodeGraphRag) {
    $Uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $Uv) { throw 'Install uv first (https://docs.astral.sh/uv/getting-started/installation/) or omit -InstallCodeGraphRag.' }
    & $Uv.Source tool install 'code-graph-rag[treesitter-full,ast-grep,semantic]'
    if ($LASTEXITCODE -ne 0) { throw 'Code-Graph-RAG installation failed; the core pilot remains independently usable.' }
}

$Config = [ordered]@{
    mcpServers = [ordered]@{
        lazytoken = [ordered]@{
            command = $Python.Source
            args = @((Join-Path $PSScriptRoot 'kn.py'), 'mcp')
            env = @{ KN_HOME = $DataRoot }
        }
    }
} | ConvertTo-Json -Depth 8
$ConfigPath = Join-Path $PSScriptRoot 'mcp_config.json'
$Config | Set-Content -LiteralPath $ConfigPath -Encoding utf8
Write-Host "Knowledge Network initialized. MCP snippet: $ConfigPath"
Write-Host "Shared local data: $DataRoot"
if (-not $ConfigureClients) { Write-Host 'Add the mcpServers entry to Antigravity and Codex using the documented client setup steps, or rerun with -ConfigureClients.' }
if ($ConfigureClients) {
    $Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $AntigravityConfig = Join-Path $env:USERPROFILE '.gemini\config\mcp_config.json'
    $AntigravityDir = Split-Path -Parent $AntigravityConfig
    New-Item -ItemType Directory -Force -Path $AntigravityDir | Out-Null
    if (Test-Path -LiteralPath $AntigravityConfig) {
        $Antigravity = Get-Content -LiteralPath $AntigravityConfig -Raw | ConvertFrom-Json
        if (-not $Antigravity.mcpServers) { $Antigravity | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) }
    } else {
        $Antigravity = [pscustomobject]@{ mcpServers = [pscustomobject]@{} }
    }
    $Entry = $Config | ConvertFrom-Json
    $Existing = $Antigravity.mcpServers.PSObject.Properties['lazytoken']
    if (-not $Existing) {
        if (Test-Path -LiteralPath $AntigravityConfig) { Copy-Item -LiteralPath $AntigravityConfig -Destination "$AntigravityConfig.$Stamp.bak" }
        $Antigravity.mcpServers | Add-Member -NotePropertyName lazytoken -NotePropertyValue $Entry.mcpServers.lazytoken
        $Antigravity | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $AntigravityConfig -Encoding utf8
    }
    $null = Get-Content -LiteralPath $AntigravityConfig -Raw | ConvertFrom-Json

    $Codex = Get-Command codex -ErrorAction SilentlyContinue
    if (-not $Codex) { throw 'Antigravity was configured, but Codex CLI was not found. Add the generated TOML entry manually; see README.md.' }
    $CodexConfig = Join-Path $env:USERPROFILE '.codex\config.toml'
    & $Codex.Source mcp get lazytoken 2>$null | Out-Null
    $CodexAlreadyConfigured = $LASTEXITCODE -eq 0
    if (-not $CodexAlreadyConfigured) {
        if (Test-Path -LiteralPath $CodexConfig) { Copy-Item -LiteralPath $CodexConfig -Destination "$CodexConfig.$Stamp.bak" }
        $AddArgs = @('mcp','add','lazytoken','--env',"KN_HOME=$DataRoot",'--',$Python.Source,(Join-Path $PSScriptRoot 'kn.py'),'mcp')
        & $Codex.Source @AddArgs | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed. Restore its timestamped backup if needed, then use the README manual setup.' }
    }
    & $Codex.Source mcp get lazytoken | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Codex did not confirm the new MCP registration.' }
    Write-Host "Antigravity and Codex MCP entries are present. Any changed settings files were backed up with a timestamp. Restart both clients to load the MCP server."
}
