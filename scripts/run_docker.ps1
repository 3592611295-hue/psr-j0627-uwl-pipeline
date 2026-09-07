param(
    [Parameter(Mandatory = $true)]
    [string]$InputFile,

    [string]$DataRoot = "C:\psrchive_work",
    [string]$ResultsDirectory = "results",
    [string]$ConfigInContainer = "/opt/pipeline/configs/j0627_uwl.example.json",
    [string]$Image = "artefact.skao.int/ska-pst-dspsr:0.3.7"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$inputInContainer = "/mnt/data/$InputFile"
$resultsInContainer = "/mnt/data/$ResultsDirectory"

docker run --rm -it `
  -v "${DataRoot}:/mnt/data" `
  -v "${repo}:/opt/pipeline:ro" `
  -w /mnt/data `
  $Image `
  bash /opt/pipeline/scripts/run_one.sh `
    $ConfigInContainer `
    $inputInContainer `
    $resultsInContainer
