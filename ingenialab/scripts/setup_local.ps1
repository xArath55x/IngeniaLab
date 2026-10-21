$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
py -3.12 scripts/setup_local.py
exit $LASTEXITCODE
