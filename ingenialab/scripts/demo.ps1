$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
py -3.12 scripts/demo.py @args
exit $LASTEXITCODE
