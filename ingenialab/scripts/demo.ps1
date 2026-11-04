Set-Location (Join-Path $PSScriptRoot '..')
foreach ($version in '3.12', '3.13', '3.11') {
    & py "-$version" -c 'import sys' 2>$null
    if ($LASTEXITCODE -eq 0) {
        & py "-$version" scripts/demo.py @args
        exit $LASTEXITCODE
    }
}
Write-Host 'Instala Python 3.11, 3.12 o 3.13.'
exit 1
