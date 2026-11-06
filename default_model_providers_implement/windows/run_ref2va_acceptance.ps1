param(
    [Parameter(Mandatory = $true)]
    [string]$Endpoint
)

$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Acceptance scripts import the Core SDK as well; inside the Slatehand repository it is the parent directory.
$env:PYTHONPATH = "$RepositoryRoot;$(Split-Path -Parent $RepositoryRoot)"
$Python = "E:\Programs\Dev\MiniForge3\envs\comfyui\python.exe"

& $Python -m scripts.ref2va_acceptance `
    --endpoint $Endpoint `
    --token-file "E:\SlatehandModelProviders\service-token.txt" `
    --first "$RepositoryRoot\tmp\ref2va-test-first.png" `
    --last "$RepositoryRoot\tmp\ref2va-test-last.png" `
    --output-dir "$RepositoryRoot\tmp\ref2va-results"
