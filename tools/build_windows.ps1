<#
.SYNOPSIS
    Build the Windows release artifacts for LM Studio Tray Manager.

.DESCRIPTION
    The Windows counterpart to tools/build_macos.sh. Creates a virtual
    environment, installs the pinned build and runtime dependencies,
    generates the application icon from the PNG asset, builds a one-file
    windowed executable with PyInstaller, and packages the result as a ZIP
    with a checksum file. An Inno Setup installer is built as well when
    ISCC.exe is available.

    Artifacts land in release\:
      lmstudio-tray-manager-<version>-windows-x86_64.zip
      lmstudio-tray-manager-<version>-windows-x86_64-setup.exe
      SHA256SUMS-windows.txt

.PARAMETER Clean
    Remove the venv, build, dist and release directories before building.

.PARAMETER SkipInstaller
    Build only the portable ZIP, even if Inno Setup is installed.

.EXAMPLE
    .\tools\build_windows.ps1 -Clean

.NOTES
    Requires Python 3.10+ on PATH. Inno Setup is optional; install it
    with:  winget install JRSoftware.InnoSetup

    Version 6 and 7 install side by side and the installer script compiles
    under either; when both are present the higher one is used.
#>

[CmdletBinding()]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute(
    'PSAvoidUsingWriteHost', '',
    Justification = 'Build progress is meant for a human watching a terminal, not for the pipeline.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute(
    'PSReviewUnusedParameter', '',
    Justification = 'Parameters are read inside the functions below, which the analyzer does not follow.')]
param(
    [switch]$Clean,
    [switch]$SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Configuration --------------------------------------------------------

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

$VenvDir = Join-Path $ProjectRoot 'venv_windows'
$BuildDir = Join-Path $ProjectRoot 'build\windows'
$DistDir = Join-Path $ProjectRoot 'dist'
$ReleaseDir = Join-Path $ProjectRoot 'release'
$IconPath = Join-Path $BuildDir 'app.ico'
$IconSource = Join-Path $ProjectRoot 'assets\img\lm-studio-tray-manager.png'
$InstallerScript = Join-Path $ScriptDir 'windows-installer.iss'

$ExeName = 'lmstudio-tray-manager.exe'
$BuiltExe = Join-Path $DistDir $ExeName

# The build is x86_64 only: PyInstaller can ship only what the host Python
# provides, and the release runners are x64. The name says so explicitly so
# an arm64 user does not download a build that cannot run natively.
$Architecture = 'x86_64'

function Write-Step {
    <#
    .SYNOPSIS
        Print a build step heading.
    .PARAMETER Message
        Heading text.
    #>
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    <#
    .SYNOPSIS
        Print a success line.
    .PARAMETER Message
        Text to print.
    #>
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "OK  $Message" -ForegroundColor Green
}

function Write-Warn {
    <#
    .SYNOPSIS
        Print a warning line.
    .PARAMETER Message
        Text to print.
    #>
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "!   $Message" -ForegroundColor Yellow
}

function Get-ProjectVersion {
    <#
    .SYNOPSIS
        Return the version from the VERSION file, without the leading "v".
    #>
    $versionFile = Join-Path $ProjectRoot 'VERSION'
    if (-not (Test-Path -PathType Leaf $versionFile)) {
        throw "VERSION file not found at $versionFile"
    }
    $version = (Get-Content $versionFile -Raw).Trim()
    return $version -replace '^v', ''
}

function Test-PythonCandidate {
    <#
    .SYNOPSIS
        Report whether an interpreter candidate actually runs.

        Windows 11 ships an App Execution Alias at
        %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe that is on PATH even
        when Python is not installed. Get-Command finds it, but running it
        only opens the Microsoft Store and exits non-zero, so a candidate is
        only accepted once it has reported a version.

    .PARAMETER File
        Interpreter path.
    .PARAMETER Prefix
        Arguments that must precede the interpreter's own, e.g. -3 for py.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [string[]]$Prefix = @()
    )

    try {
        & $File @Prefix '--version' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-PythonPath {
    <#
    .SYNOPSIS
        Return a usable Python interpreter, preferring the py launcher.
    #>
    $launcher = Get-Command 'py' -CommandType Application -ErrorAction SilentlyContinue
    if ($launcher -and (Test-PythonCandidate -File $launcher.Source -Prefix @('-3'))) {
        return @{ File = $launcher.Source; Prefix = @('-3') }
    }

    # Every match is considered, not just the first: the Store alias often
    # sits on PATH ahead of a real installation.
    $candidates = @(Get-Command 'python' -CommandType Application -All -ErrorAction SilentlyContinue)
    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -File $candidate.Source) {
            return @{ File = $candidate.Source; Prefix = @() }
        }
    }

    if ($candidates.Count -gt 0) {
        throw (
            'Found python on PATH but it is not a working interpreter ' +
            '(likely the Microsoft Store alias). Install Python 3.10 or ' +
            'newer from python.org, or disable the alias under Settings > ' +
            'Apps > Advanced app settings > App execution aliases.'
        )
    }
    throw 'No Python interpreter found on PATH. Install Python 3.10 or newer.'
}

function Invoke-Clean {
    <#
    .SYNOPSIS
        Remove build output from a previous run.
    #>
    Write-Step 'Cleaning previous builds'
    foreach ($directory in @($VenvDir, (Join-Path $ProjectRoot 'build'), $DistDir, $ReleaseDir)) {
        if (Test-Path $directory) {
            Remove-Item -Recurse -Force -Path $directory
        }
    }
    Write-Ok 'Cleaned'
}

function Initialize-Venv {
    <#
    .SYNOPSIS
        Create the virtual environment and install pinned dependencies.

        Returns the path to the venv's python.exe.
    #>
    Write-Step 'Preparing the virtual environment'

    $venvPython = Join-Path $VenvDir 'Scripts\python.exe'
    if (-not (Test-Path -PathType Leaf $venvPython)) {
        $python = Get-PythonPath
        & $python.File @($python.Prefix) -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create the virtual environment' }
    }

    & $venvPython -m pip install --upgrade pip setuptools wheel --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Failed to upgrade pip' }

    # Build dependencies are hash-locked; the Windows runtime dependencies
    # are pinned but hash-free so scanners can read them, matching how the
    # macOS build treats rumps.
    & $venvPython -m pip install --require-hashes -r (Join-Path $ProjectRoot 'requirements-build.txt') --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install build dependencies' }

    & $venvPython -m pip install -r (Join-Path $ProjectRoot 'requirements-windows.txt') --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install Windows runtime dependencies' }

    Write-Ok 'Dependencies installed'
    return $venvPython
}

function New-AppIcon {
    <#
    .SYNOPSIS
        Generate a multi-resolution .ico from the PNG asset.

        Generated rather than committed so the repository carries no binary
        icon blob. Building without it is allowed; the executable then uses
        the default PyInstaller icon, which is cosmetic only.

    .PARAMETER VenvPython
        Interpreter that has Pillow installed.
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Build-script step writing to its own build directory; -WhatIf on a build has no meaning.')]
    param([Parameter(Mandatory = $true)][string]$VenvPython)

    Write-Step 'Generating the application icon'

    if (-not (Test-Path -PathType Leaf $IconSource)) {
        Write-Warn "Icon source not found at $IconSource - building without a custom icon"
        return
    }

    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

    # A literal here-string, with the paths handed over as arguments. They
    # used to be interpolated into Python string literals, which a checkout
    # under a path like "C:\User's Git" turned into a SyntaxError.
    $generator = @'
"""Generate a multi-resolution .ico from a PNG. Written by build_windows.ps1."""

import sys

from PIL import Image

source = Image.open(sys.argv[1]).convert('RGBA')
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
source.save(sys.argv[2], format='ICO', sizes=sizes)
'@

    $generatorPath = Join-Path $BuildDir 'make_icon.py'
    Set-Content -Path $generatorPath -Value $generator -Encoding utf8

    & $VenvPython $generatorPath $IconSource $IconPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -PathType Leaf $IconPath)) {
        Write-Warn 'Icon generation failed - building without a custom icon'
        return
    }

    Write-Ok "Icon generated: $IconPath"
}

function Invoke-PyInstaller {
    <#
    .SYNOPSIS
        Build the one-file executable.
    .PARAMETER VenvPython
        Interpreter with PyInstaller installed.
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPython)

    Write-Step 'Building the executable'

    Push-Location $ProjectRoot
    try {
        & $VenvPython (Join-Path $ScriptDir 'build_binary.py')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    } finally {
        Pop-Location
    }

    if (-not (Test-Path -PathType Leaf $BuiltExe)) {
        throw "Build reported success but $BuiltExe is missing"
    }

    Write-Ok "Built $BuiltExe"
}

function Test-BuiltExe {
    <#
    .SYNOPSIS
        Check that the built executable starts and exits cleanly.

        A windowed build has no console, so --version writes nowhere unless
        it can reattach the caller's console. The exit code is the reliable
        signal and is what is asserted here.

        Start-Process -Wait rather than calling the exe directly: the direct
        form does return the right code when this script runs in a console,
        but a GUI-subsystem process started from a session without one has
        nothing to attach to, and the wait is then not guaranteed. This also
        matches how the CI workflow smoke-tests the same binary.
    #>
    Write-Step 'Smoke-testing the executable'

    $process = Start-Process -FilePath $BuiltExe -ArgumentList '--version' `
        -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) {
        throw "The built executable exited with $($process.ExitCode) for --version"
    }

    Write-Ok 'Executable starts and exits cleanly'
}

function New-PortableZip {
    <#
    .SYNOPSIS
        Package the executable and its companion files as a ZIP.

        Returns the path to the created archive.
    .PARAMETER Version
        Release version, without the leading "v".
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Build-script step writing to its own release directory; -WhatIf on a build has no meaning.')]
    param([Parameter(Mandatory = $true)][string]$Version)

    Write-Step 'Packaging the portable ZIP'

    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

    $stageDir = Join-Path $BuildDir 'stage'
    if (Test-Path $stageDir) { Remove-Item -Recurse -Force $stageDir }
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

    Copy-Item $BuiltExe -Destination $stageDir
    foreach ($name in @('lmstudio_autostart.ps1', 'VERSION', 'AUTHORS', 'LICENSE', 'README.md')) {
        $source = Join-Path $ProjectRoot $name
        if (Test-Path -PathType Leaf $source) {
            Copy-Item $source -Destination $stageDir
        } else {
            Write-Warn "Not found, omitted from the archive: $name"
        }
    }

    $zipPath = Join-Path $ReleaseDir "lmstudio-tray-manager-$Version-windows-$Architecture.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    Compress-Archive -Path (Join-Path $stageDir '*') -DestinationPath $zipPath

    Write-Ok "Created $zipPath"
    return $zipPath
}

function New-Installer {
    <#
    .SYNOPSIS
        Build the Inno Setup installer, if Inno Setup is available.

        Returns the path to the installer, or $null when it was skipped.
    .PARAMETER Version
        Release version, without the leading "v".
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Build-script step writing to its own release directory; -WhatIf on a build has no meaning.')]
    param([Parameter(Mandatory = $true)][string]$Version)

    Write-Step 'Building the installer'

    if ($SkipInstaller) {
        Write-Warn 'Skipped on request (-SkipInstaller)'
        return $null
    }

    # Inno Setup does not put ISCC on PATH, and winget installs it per-user
    # unless it is run elevated, so all three roots are checked.
    #
    # The directory carries the major version ("Inno Setup 6", "Inno Setup 7"),
    # and 6 and 7 install side by side, so the roots are searched with a
    # wildcard and the highest major wins. Pinning to 6 here meant a machine
    # with only 7 installed silently produced no installer at all.
    $iscc = Get-Command 'ISCC' -CommandType Application -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $roots = @(
            (Join-Path $env:LOCALAPPDATA 'Programs'),
            ${env:ProgramFiles(x86)},
            $env:ProgramFiles
        ) | Where-Object { $_ -and (Test-Path -PathType Container $_) }

        $found = foreach ($root in $roots) {
            Get-ChildItem -Path $root -Filter 'Inno Setup *' -Directory `
                -ErrorAction SilentlyContinue |
                ForEach-Object {
                    $exe = Join-Path $_.FullName 'ISCC.exe'
                    if (Test-Path -PathType Leaf $exe) {
                        $major = 0
                        if ($_.Name -match 'Inno Setup (\d+)') {
                            $major = [int]$Matches[1]
                        }
                        [pscustomobject]@{ Major = $major; Source = $exe }
                    }
                }
        }

        $best = $found | Sort-Object Major -Descending | Select-Object -First 1
        if ($best) { $iscc = @{ Source = $best.Source } }
    }

    if (-not $iscc) {
        Write-Warn 'Inno Setup (ISCC.exe) not found - skipping the installer'
        Write-Warn 'Install it with:  winget install JRSoftware.InnoSetup'
        return $null
    }

    Write-Host "    Using $($iscc.Source)"

    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

    # Piped to Write-Host rather than left on the pipeline: this function
    # returns the installer path, and ISCC's console output would otherwise
    # be part of that return value.
    & $iscc.Source `
        "/DAppVersion=$Version" `
        "/DProjectRoot=$ProjectRoot" `
        "/DArchitecture=$Architecture" `
        "/O$ReleaseDir" `
        $InstallerScript | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup build failed' }

    $installerPath = Join-Path $ReleaseDir "lmstudio-tray-manager-$Version-windows-$Architecture-setup.exe"
    if (-not (Test-Path -PathType Leaf $installerPath)) {
        throw "Inno Setup reported success but $installerPath is missing"
    }

    Write-Ok "Created $installerPath"
    return $installerPath
}

function New-ChecksumFile {
    <#
    .SYNOPSIS
        Write SHA256SUMS-windows.txt covering the release artifacts.
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Build-script step writing to its own release directory; -WhatIf on a build has no meaning.')]
    param()

    Write-Step 'Writing checksums'

    $checksumFile = Join-Path $ReleaseDir 'SHA256SUMS-windows.txt'
    $lines = Get-ChildItem -Path $ReleaseDir -File |
        Where-Object { $_.Name -ne 'SHA256SUMS-windows.txt' } |
        Sort-Object Name |
        ForEach-Object {
            $hash = (Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLower()
            # Two spaces and a leading name, matching sha256sum output so
            # `sha256sum -c` accepts the file on any platform.
            "$hash  $($_.Name)"
        }

    Set-Content -Path $checksumFile -Value $lines -Encoding ascii
    Write-Ok "Created $checksumFile"
    $lines | ForEach-Object { Write-Host "    $_" }
}

# --- Main -----------------------------------------------------------------

if ($Clean) { Invoke-Clean }

$version = Get-ProjectVersion
Write-Host "Building LM Studio Tray Manager $version for windows-$Architecture"

$venvPython = Initialize-Venv
New-AppIcon -VenvPython $venvPython
Invoke-PyInstaller -VenvPython $venvPython
Test-BuiltExe
New-PortableZip -Version $version | Out-Null
New-Installer -Version $version | Out-Null
New-ChecksumFile

Write-Step 'Done'
Get-ChildItem -Path $ReleaseDir -File | Format-Table Name, Length -AutoSize
