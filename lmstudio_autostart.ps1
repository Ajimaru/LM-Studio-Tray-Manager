<#
.SYNOPSIS
    Starts the LM Studio tray monitor on Windows, and optionally registers
    it to start with Windows.

.DESCRIPTION
    The Windows counterpart to lmstudio_autostart.sh. Default behaviour
    (without -Gui): start llmster (the headless daemon) and the tray
    monitor. With -Gui: stop llmster if it is running, then start the LM
    Studio desktop app and the tray monitor.

    Deliberately narrower than the Bash script. There is no package-manager
    automation and no venv handling: Windows users get a portable .exe or
    an installer, so a missing dependency is reported with the winget id
    rather than installed behind the user's back.

    The log file is recreated per run under
    %LOCALAPPDATA%\lmstudio-tray-manager\logs\lmstudio_autostart.log

.PARAMETER Gui
    Stop the daemon if running, then start the LM Studio desktop app
    together with the tray monitor.

.PARAMETER ListModels
    List local models without starting LM Studio, then exit.

.PARAMETER Model
    Model name to hand to the tray monitor.

.PARAMETER DebugMode
    Enable verbose output, to the console as well as the log. Named
    DebugMode because -Debug is a reserved common parameter.

.PARAMETER InstallAutostart
    Create a shortcut in the user's Startup folder so the tray starts with
    Windows, then exit.

.PARAMETER UninstallAutostart
    Remove that shortcut again, then exit.

.EXAMPLE
    .\lmstudio_autostart.ps1
    Start the daemon and the tray monitor.

.EXAMPLE
    .\lmstudio_autostart.ps1 -Gui
    Stop the daemon, then start the desktop app and the tray monitor.

.EXAMPLE
    .\lmstudio_autostart.ps1 -InstallAutostart
    Register the tray to start with Windows.

.NOTES
    Exit codes:
      0  Success
      1  Setup failed
      2  Invalid option/usage
      3  No models found (-ListModels)
#>

[CmdletBinding()]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute(
    'PSReviewUnusedParameter', '',
    Justification = 'Parameters are read inside the functions below, which the analyzer does not follow.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute(
    'PSAvoidUsingWriteHost', '',
    Justification = 'Write-TrayLog deliberately writes coloured progress to the console; its output is not pipeline data.')]
param(
    [switch]$Gui,
    [switch]$ListModels,
    [string]$Model,
    [switch]$DebugMode,
    [switch]$InstallAutostart,
    [switch]$UninstallAutostart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Settings -------------------------------------------------------------

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppName = 'LM Studio Tray Manager'
$ShortcutName = 'LM Studio Tray Manager.lnk'
$TrayExeName = 'lmstudio-tray-manager.exe'
$TrayScriptName = 'lmstudio_tray.py'
$DaemonImage = 'llmster.exe'

$DataDir = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA 'lmstudio-tray-manager'
} else {
    Join-Path $HOME 'AppData\Local\lmstudio-tray-manager'
}
$LogDir = Join-Path $DataDir 'logs'
$LogFile = Join-Path $LogDir 'lmstudio_autostart.log'

if ($env:LM_AUTOSTART_DEBUG -eq '1') { $DebugMode = $true }

# --- Logging --------------------------------------------------------------

function Initialize-Log {
    <#
    .SYNOPSIS
        Create the log directory and start a fresh log file for this run.
    #>
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    }
    $header = @(
        ('=' * 80),
        'LM Studio Autostart Log',
        "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        ('=' * 80)
    )
    Set-Content -Path $LogFile -Value $header -Encoding utf8
}

function Write-TrayLog {
    <#
    .SYNOPSIS
        Append a line to the log, and echo it to the console.
    .PARAMETER Message
        Text to record.
    .PARAMETER Level
        Severity label: INFO, WARN, ERROR or DEBUG.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet('INFO', 'WARN', 'ERROR', 'DEBUG')][string]$Level = 'INFO'
    )

    if ($Level -eq 'DEBUG' -and -not $DebugMode) { return }

    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    # The home directory is masked the same way the tray's log formatter
    # does it, so a log can be pasted into an issue as-is.
    $masked = $Message
    if ($HOME) { $masked = $masked.Replace($HOME, '~') }
    Add-Content -Path $LogFile -Value "$stamp - $Level - $masked" -Encoding utf8

    switch ($Level) {
        'ERROR' { Write-Host "[ERROR] $masked" -ForegroundColor Red }
        'WARN' { Write-Host "[WARN ] $masked" -ForegroundColor Yellow }
        'DEBUG' { Write-Host "[DEBUG] $masked" -ForegroundColor DarkGray }
        default { Write-Host "[INFO ] $masked" }
    }
}

# --- Command discovery ----------------------------------------------------

function Get-CommandPath {
    <#
    .SYNOPSIS
        Return the full path of a command on PATH, or $null.
    .PARAMETER Name
        Command to look for.
    #>
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { return $command.Source | Select-Object -First 1 }
    return $null
}

function Get-LmsPath {
    <#
    .SYNOPSIS
        Return the path to the lms CLI, preferring the bundled copy.
    #>
    $bundled = Join-Path $HOME '.lmstudio\bin\lms.exe'
    if (Test-Path -PathType Leaf $bundled) { return $bundled }
    return Get-CommandPath 'lms'
}

function Get-LlmsterPath {
    <#
    .SYNOPSIS
        Return the path to the llmster daemon binary, or $null.

        Mirrors the tray's own resolution order: PATH first, then the
        highest-sorting version under ~\.lmstudio\llmster.
    #>
    $onPath = Get-CommandPath 'llmster'
    if ($onPath) { return $onPath }

    $root = Join-Path $HOME '.lmstudio\llmster'
    if (-not (Test-Path -PathType Container $root)) { return $null }

    $candidate = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name |
        ForEach-Object { Join-Path $_.FullName 'llmster.exe' } |
        Where-Object { Test-Path -PathType Leaf $_ } |
        Select-Object -Last 1

    return $candidate
}

function Get-LmStudioPath {
    <#
    .SYNOPSIS
        Return the path to the LM Studio desktop executable, or $null.
    #>
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\LM Studio\LM Studio.exe'),
        (Join-Path $env:ProgramFiles 'LM Studio\LM Studio.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -PathType Leaf $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Get-TrayCommand {
    <#
    .SYNOPSIS
        Return how to launch the tray: the frozen exe, or Python plus the
        script.

        Returns a hashtable with File and Arguments, or $null when neither
        is available.
    #>
    $exe = Join-Path $ScriptDir $TrayExeName
    if (Test-Path -PathType Leaf $exe) {
        return @{ File = $exe; Arguments = @() }
    }

    $script = Join-Path $ScriptDir $TrayScriptName
    if (-not (Test-Path -PathType Leaf $script)) { return $null }

    # pythonw runs the tray without a console window, which is what a
    # background tray app wants; python is the fallback.
    foreach ($name in @('pythonw', 'python', 'py')) {
        $interpreter = Get-CommandPath $name
        if ($interpreter) {
            $arguments = if ($name -eq 'py') { @('-3', $script) } else { @($script) }
            return @{ File = $interpreter; Arguments = $arguments }
        }
    }
    return $null
}

# --- Dependency checks ----------------------------------------------------

function Test-Environment {
    <#
    .SYNOPSIS
        Report what is installed, and whether the tray can start at all.

        Returns $true when the tray is launchable. Missing LM Studio parts
        are reported with the winget id rather than installed silently.
    #>
    $ok = $true

    $tray = Get-TrayCommand
    if ($tray) {
        Write-TrayLog "Tray launcher: $($tray.File)" 'DEBUG'
    } else {
        Write-TrayLog "Neither $TrayExeName nor $TrayScriptName found in $ScriptDir" 'ERROR'
        Write-TrayLog 'Run this script from the directory it was installed into.' 'ERROR'
        $ok = $false
    }

    $lms = Get-LmsPath
    if ($lms) {
        Write-TrayLog "LM Studio CLI: $lms" 'DEBUG'
    } else {
        Write-TrayLog 'LM Studio CLI (lms) not found on PATH.' 'WARN'
    }

    $llmster = Get-LlmsterPath
    if ($llmster) {
        Write-TrayLog "llmster daemon: $llmster" 'DEBUG'
    } else {
        Write-TrayLog 'llmster daemon not found; the headless daemon cannot be started.' 'WARN'
    }

    $desktop = Get-LmStudioPath
    if ($desktop) {
        Write-TrayLog "LM Studio desktop app: $desktop" 'DEBUG'
    } else {
        Write-TrayLog 'LM Studio desktop app not found.' 'WARN'
        Write-TrayLog 'Install it with:  winget install ElementLabs.LMStudio' 'WARN'
    }

    if (-not $lms -and -not $llmster -and -not $desktop) {
        Write-TrayLog 'No LM Studio installation detected at all.' 'ERROR'
        Write-TrayLog 'Download it from https://lmstudio.ai/download' 'ERROR'
        $ok = $false
    }

    return $ok
}

# --- Model listing --------------------------------------------------------

function Get-ModelLabel {
    <#
    .SYNOPSIS
        Turn a model file path into a readable label.
    .PARAMETER Path
        Path to a model file or manifest.
    #>
    param([Parameter(Mandatory = $true)][string]$Path)

    $leaf = Split-Path -Leaf $Path
    if ($leaf -eq 'manifest.json') {
        # A manifest sits at <publisher>\<model>\manifest.json, so the two
        # directories above it are the name worth showing.
        $parent = Split-Path -Leaf (Split-Path -Parent $Path)
        $grand = Split-Path -Leaf (Split-Path -Parent (Split-Path -Parent $Path))
        return "$grand/$parent"
    }
    return $leaf
}

function Show-ModelList {
    <#
    .SYNOPSIS
        List local models without starting LM Studio.

        Returns 0 when models were found, 3 when none were.
    #>
    Write-Host 'Local models (without starting LM Studio):'
    $found = $false

    $lms = Get-LmsPath
    if ($lms) {
        foreach ($arguments in @(@('models', 'list'), @('list'))) {
            $output = & $lms @arguments 2>$null
            if ($LASTEXITCODE -eq 0 -and $output) {
                Write-Host "Source: lms ($lms)"
                $output | ForEach-Object { Write-Host $_ }
                $found = $true
                break
            }
        }
    }

    $directories = @(
        (Join-Path $HOME '.lmstudio\models'),
        (Join-Path $HOME '.lmstudio\hub\models'),
        (Join-Path $HOME 'LM Studio\models'),
        (Join-Path $ScriptDir 'models')
    )
    $patterns = @('*.gguf', '*.bin', '*.safetensors', 'manifest.json')

    foreach ($directory in $directories) {
        if (-not (Test-Path -PathType Container $directory)) { continue }

        $files = Get-ChildItem -Path $directory -Recurse -File -Depth 6 `
            -Include $patterns -ErrorAction SilentlyContinue
        if (-not $files) { continue }

        Write-Host "Source: $directory"
        foreach ($file in $files) {
            Write-Host " - $(Get-ModelLabel $file.FullName)  [$($file.FullName)]"
        }
        $found = $true
    }

    if (-not $found) {
        Write-Host 'No local models found.'
        return 3
    }
    return 0
}

# --- Daemon and desktop app -----------------------------------------------

function Test-DaemonRunning {
    <#
    .SYNOPSIS
        Report whether the llmster daemon is running.
    #>
    $process = Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($DaemonImage)) `
        -ErrorAction SilentlyContinue
    return [bool]$process
}

function Start-Daemon {
    <#
    .SYNOPSIS
        Start the llmster headless daemon.

        Returns $true when the daemon is running afterwards.
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Internal helper of a script whose whole purpose is to start the daemon; -WhatIf belongs on the script, not here.')]
    param()

    if (Test-DaemonRunning) {
        Write-TrayLog 'llmster daemon is already running'
        return $true
    }

    $llmster = Get-LlmsterPath
    if (-not $llmster) {
        Write-TrayLog 'llmster not installed; cannot start the headless daemon.' 'ERROR'
        return $false
    }

    # lms is deliberately not tried here: where LM Studio embeds the daemon,
    # `lms daemon up` launches the desktop app instead of a headless daemon.
    foreach ($arguments in @(@('daemon', 'up'), @('daemon', 'start'), @('up'), @('start'))) {
        Write-TrayLog "Trying: $llmster $($arguments -join ' ')" 'DEBUG'
        & $llmster @arguments 2>$null | Out-Null

        for ($i = 0; $i -lt 10; $i++) {
            if (Test-DaemonRunning) {
                Write-TrayLog 'llmster daemon started'
                return $true
            }
            Start-Sleep -Milliseconds 500
        }
    }

    Write-TrayLog 'Daemon start failed' 'ERROR'
    return $false
}

function Stop-Daemon {
    <#
    .SYNOPSIS
        Stop the llmster daemon, escalating to a forced kill if needed.

        Returns $true when the daemon is no longer running.
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Internal helper; the caller decides whether stopping the daemon happens at all.')]
    param()

    if (-not (Test-DaemonRunning)) { return $true }

    $lms = Get-LmsPath
    if ($lms) {
        foreach ($arguments in @(@('daemon', 'down'), @('daemon', 'stop'))) {
            & $lms @arguments 2>$null | Out-Null
            if (-not (Test-DaemonRunning)) {
                Write-TrayLog 'llmster daemon stopped'
                return $true
            }
        }
    }

    & taskkill.exe /IM $DaemonImage /T 2>$null | Out-Null
    for ($i = 0; $i -lt 12; $i++) {
        if (-not (Test-DaemonRunning)) {
            Write-TrayLog 'llmster daemon stopped'
            return $true
        }
        Start-Sleep -Milliseconds 250
    }

    Write-TrayLog 'Daemon did not stop gracefully; forcing termination' 'WARN'
    & taskkill.exe /IM $DaemonImage /T /F 2>$null | Out-Null
    Start-Sleep -Milliseconds 500

    if (Test-DaemonRunning) {
        Write-TrayLog 'Failed to stop the llmster daemon' 'ERROR'
        return $false
    }
    return $true
}

function Start-DesktopApp {
    <#
    .SYNOPSIS
        Start the LM Studio desktop app.

        Returns $true when it was launched.
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Internal helper reached only when the caller passed -Gui.')]
    param()

    $exe = if ($env:LM_AUTOSTART_GUI_CMD) {
        $env:LM_AUTOSTART_GUI_CMD
    } else {
        Get-LmStudioPath
    }

    if (-not $exe) {
        Write-TrayLog 'LM Studio desktop app not found.' 'ERROR'
        Write-TrayLog 'Download it from https://lmstudio.ai/download' 'ERROR'
        return $false
    }

    Write-TrayLog "Starting LM Studio: $exe"
    Start-Process -FilePath $exe | Out-Null
    return $true
}

function Start-Tray {
    <#
    .SYNOPSIS
        Start the tray monitor.

        Returns $true when it was launched.
    #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute(
        'PSUseShouldProcessForStateChangingFunctions', '',
        Justification = 'Internal helper; starting the tray is the scripts default action.')]
    param()

    $tray = Get-TrayCommand
    if (-not $tray) {
        Write-TrayLog 'Tray monitor not found; nothing to start.' 'ERROR'
        return $false
    }

    $arguments = @($tray.Arguments)
    if ($Model) { $arguments += $Model }
    if ($DebugMode) { $arguments += '--debug' }

    Write-TrayLog "Starting tray monitor: $($tray.File) $($arguments -join ' ')"
    if ($arguments.Count -gt 0) {
        Start-Process -FilePath $tray.File -ArgumentList $arguments | Out-Null
    } else {
        Start-Process -FilePath $tray.File | Out-Null
    }
    return $true
}

# --- Autostart registration -----------------------------------------------

function Get-StartupShortcutPath {
    <#
    .SYNOPSIS
        Return the path of the Startup-folder shortcut for this user.
    #>
    $startup = [Environment]::GetFolderPath('Startup')
    return Join-Path $startup $ShortcutName
}

function Install-Autostart {
    <#
    .SYNOPSIS
        Create the Startup-folder shortcut so the tray starts with Windows.

        A Startup shortcut is used rather than a Run registry value or a
        scheduled task: it needs no elevation, and the user can see and
        remove it from the Startup folder without this script.

        Returns 0 on success, 1 on failure.
    #>
    $tray = Get-TrayCommand
    if (-not $tray) {
        Write-TrayLog 'Tray monitor not found; nothing to register.' 'ERROR'
        return 1
    }

    $shortcutPath = Get-StartupShortcutPath
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $tray.File
    $shortcut.Arguments = ($tray.Arguments -join ' ')
    $shortcut.WorkingDirectory = $ScriptDir
    $shortcut.Description = "$AppName - LM Studio status in the notification area"
    $shortcut.Save()

    Write-TrayLog "Autostart enabled: $shortcutPath"
    return 0
}

function Uninstall-Autostart {
    <#
    .SYNOPSIS
        Remove the Startup-folder shortcut.

        Returns 0 whether or not a shortcut was present: the requested end
        state is "not registered", which is already true if it is absent.
    #>
    $shortcutPath = Get-StartupShortcutPath
    if (Test-Path -PathType Leaf $shortcutPath) {
        Remove-Item -Path $shortcutPath -Force
        Write-TrayLog "Autostart disabled: $shortcutPath"
    } else {
        Write-TrayLog 'Autostart was not enabled; nothing to remove.'
    }
    return 0
}

# --- Main -----------------------------------------------------------------

function Invoke-Main {
    <#
    .SYNOPSIS
        Dispatch on the parameters and return the process exit code.
    #>
    if ($InstallAutostart -and $UninstallAutostart) {
        Write-TrayLog 'Use either -InstallAutostart or -UninstallAutostart, not both.' 'ERROR'
        return 2
    }

    Initialize-Log
    Write-TrayLog "Script directory: $ScriptDir" 'DEBUG'

    if ($ListModels) { return Show-ModelList }
    if ($InstallAutostart) { return Install-Autostart }
    if ($UninstallAutostart) { return Uninstall-Autostart }

    if (-not (Test-Environment)) { return 1 }

    if ($Gui) {
        # The daemon and the desktop app both bind the same API port, so
        # only one of them may run.
        if (Test-DaemonRunning) {
            Write-TrayLog 'Stopping the daemon before starting the desktop app'
            if (-not (Stop-Daemon)) { return 1 }
        }
        if (-not (Start-DesktopApp)) { return 1 }
    } else {
        if (-not (Start-Daemon)) {
            Write-TrayLog 'Continuing without the daemon; the tray will report its status.' 'WARN'
        }
    }

    if (-not (Start-Tray)) { return 1 }

    Write-TrayLog 'Done'
    return 0
}

exit (Invoke-Main)
