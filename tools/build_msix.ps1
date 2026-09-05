<#
.SYNOPSIS
    Package the Windows build as an MSIX for Microsoft Store submission or
    local sideload testing.

.DESCRIPTION
    Not part of the automatic release pipeline: Store submission itself is a
    manual Partner Center action. Run tools\build_windows.ps1 first - this
    script packages its output, it does not rebuild it.

.PARAMETER SignScript
    Path to a script invoked as `& $SignScript <file>` to sign the .msix.
    Optional: only needed for local sideload testing (Get-AppxPackage
    -AllUsers... / Add-AppxPackage refuses an unsigned or untrusted-cert
    package). Partner Center re-signs on Store submission, so this is not
    required for a Store upload.

.EXAMPLE
    .\tools\build_windows.ps1 -Clean
    .\tools\build_msix.ps1
#>

[CmdletBinding()]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute(
    'PSAvoidUsingWriteHost', '',
    Justification = 'Build progress is meant for a human watching a terminal, not for the pipeline.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute(
    'PSReviewUnusedParameter', '',
    Justification = 'SignScript is read inside Invoke-CodeSign below, which the analyzer does not follow.')]
param(
    [string]$SignScript
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$DistDir = Join-Path $ProjectRoot 'dist'
$ReleaseDir = Join-Path $ProjectRoot 'release'
$MsixSourceDir = Join-Path $ScriptDir 'windows-msix'
$ManifestSource = Join-Path $MsixSourceDir 'Package.appxmanifest'
$BuildDir = Join-Path $ProjectRoot 'build\msix'
$StageDir = Join-Path $BuildDir 'stage'
$IconSource = Join-Path $ProjectRoot 'assets\img\lm-studio-tray-manager.png'
$ExeName = 'lmstudio-tray-manager.exe'
$Architecture = 'x86_64'

function Write-Step { param([string]$Message) Write-Host ''; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok { param([string]$Message) Write-Host "OK  $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "!   $Message" -ForegroundColor Yellow }

function Get-ProjectVersion {
    $versionFile = Join-Path $ProjectRoot 'VERSION'
    if (-not (Test-Path -PathType Leaf $versionFile)) { throw "VERSION file not found at $versionFile" }
    return (Get-Content $versionFile -Raw).Trim() -replace '^v', ''
}

function New-MsixAssetSet {
    <#
    .SYNOPSIS
        Generate the fixed-size PNGs an MSIX manifest requires, from the
        same source PNG build_windows.ps1 uses for the .ico. Generated
        rather than committed, same reasoning as the .ico: no binary icon
        blob in the repository.
    .PARAMETER VenvPython
        Interpreter with Pillow installed.
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Build-script step writing to its own build directory; -WhatIf on a build has no meaning.')]
    param([Parameter(Mandatory = $true)][string]$VenvPython)

    Write-Step 'Generating MSIX icon assets'

    if (-not (Test-Path -PathType Leaf $IconSource)) {
        throw "Icon source not found at $IconSource"
    }

    $assetsDir = Join-Path $StageDir 'Assets'
    New-Item -ItemType Directory -Force -Path $assetsDir | Out-Null

    $generator = @'
"""Generate fixed-size MSIX asset PNGs from a source PNG. Written by build_msix.ps1."""

import sys

from PIL import Image

source = Image.open(sys.argv[1]).convert('RGBA')
targets = {
    'Square44x44Logo.png': 44,
    'Square150x150Logo.png': 150,
    'StoreLogo.png': 50,
}
for name, size in targets.items():
    source.resize((size, size), Image.LANCZOS).save(sys.argv[2] + '/' + name)
'@

    # Written outside $StageDir: makeappx packs everything it finds in the
    # staging directory, so a helper script left there ships to the Store.
    $generatorPath = Join-Path $BuildDir 'make_msix_assets.py'
    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
    Set-Content -Path $generatorPath -Value $generator -Encoding utf8

    & $VenvPython $generatorPath $IconSource $assetsDir
    if ($LASTEXITCODE -ne 0) { throw 'MSIX asset generation failed' }

    Write-Ok "Assets generated in $assetsDir"
}

function Find-MakeAppx {
    <#
    .SYNOPSIS
        Locate makeappx.exe from an installed Windows SDK.

        Not on PATH by default; SDKs install side by side under a
        version-numbered directory, same shape as the Inno Setup lookup in
        build_windows.ps1, so the highest version found wins.
    #>
    $cmd = Get-Command 'makeappx' -CommandType Application -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    if (-not (Test-Path -PathType Container $sdkRoot)) {
        throw (
            'makeappx.exe not found. Install the Windows SDK ' +
            '(winget install Microsoft.WindowsSDK.10.0.22621) and retry.'
        )
    }

    $found = Get-ChildItem -Path $sdkRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' } |
        ForEach-Object {
            $exe = Join-Path $_.FullName 'x64\makeappx.exe'
            if (Test-Path -PathType Leaf $exe) {
                [pscustomobject]@{ Version = [version]$_.Name; Source = $exe }
            }
        }

    $best = $found | Sort-Object Version -Descending | Select-Object -First 1
    if (-not $best) {
        throw (
            'makeappx.exe not found under Windows Kits. Install the Windows ' +
            'SDK (winget install Microsoft.WindowsSDK.10.0.22621) and retry.'
        )
    }
    return $best.Source
}

function Invoke-CodeSign {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not $SignScript) {
        Write-Warn "Skipping code signing (no -SignScript provided): $Path"
        Write-Warn 'An unsigned .msix can be uploaded to Partner Center, but cannot be sideloaded locally.'
        return
    }

    Write-Step "Signing $Path"
    & $SignScript $Path
    if ($LASTEXITCODE -ne 0) { throw "Signing failed for $Path" }
    Write-Ok "Signed $Path"
}

# --- Main -----------------------------------------------------------------

$builtExe = Join-Path $DistDir $ExeName
if (-not (Test-Path -PathType Leaf $builtExe)) {
    throw "$builtExe not found. Run tools\build_windows.ps1 first."
}

$version = Get-ProjectVersion
Write-Host "Packaging LM Studio Tray Manager $version as MSIX ($Architecture)"

if (Test-Path $StageDir) { Remove-Item -Recurse -Force $StageDir }
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

# Reuses the same venv build_windows.ps1 creates (has Pillow); creates its
# own only if that one is missing, e.g. this script is run standalone.
$venvPython = Join-Path $ProjectRoot 'venv_windows\Scripts\python.exe'
if (-not (Test-Path -PathType Leaf $venvPython)) {
    Write-Step 'Preparing a virtual environment for icon generation'
    $venvDir = Join-Path $ProjectRoot 'venv_windows'
    python -m venv $venvDir
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    & $venvPython -m pip install --require-hashes -r (Join-Path $ProjectRoot 'requirements-build.txt') --quiet
}

New-MsixAssetSet -VenvPython $venvPython

Write-Step 'Staging package contents'
Copy-Item $builtExe -Destination $StageDir
(Get-Content -Raw $ManifestSource) -replace 'Version="0\.0\.0\.0"', "Version=`"$version.0`"" |
    Set-Content -Path (Join-Path $StageDir 'AppxManifest.xml') -Encoding utf8
Write-Ok "Staged in $StageDir"

Write-Step 'Building the MSIX package'
$makeappx = Find-MakeAppx
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$msixPath = Join-Path $ReleaseDir "lmstudio-tray-manager-$version-windows-$Architecture.msix"
if (Test-Path $msixPath) { Remove-Item -Force $msixPath }

& $makeappx pack /d $StageDir /p $msixPath /o
if ($LASTEXITCODE -ne 0) { throw 'makeappx pack failed' }
Write-Ok "Created $msixPath"

Invoke-CodeSign -Path $msixPath

Write-Step 'Done'
Write-Host 'Next: upload this .msix to Partner Center under your reserved app, or'
Write-Host 'sideload-test it locally with Add-AppxPackage after signing with a cert'
Write-Host 'trusted on this machine.'
