$ErrorActionPreference = 'Stop'
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { throw 'Python is not on PATH. Install Python 3.11 or newer, then reopen PowerShell.' }
$Version = & $Python.Source -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
if ($LASTEXITCODE -ne 0 -or [version]$Version -lt [version]'3.11') { throw "Python 3.11+ required; found $Version" }
& $Python.Source (Join-Path $PSScriptRoot 'dashboard.py') @args
exit $LASTEXITCODE
