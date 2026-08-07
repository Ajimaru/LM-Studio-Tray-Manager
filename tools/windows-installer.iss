; Inno Setup script for LM Studio Tray Manager.
;
; Not built directly - tools/build_windows.ps1 supplies AppVersion,
; ProjectRoot and Architecture on the ISCC command line, so the version
; never has to be maintained in two places.
;
;   ISCC /DAppVersion=0.6.5 /DProjectRoot=D:\path\to\repo /DArchitecture=x86_64 ^
;        /O<output dir> tools\windows-installer.iss

#ifndef AppVersion
  #error AppVersion must be passed with /DAppVersion=<version>
#endif

#ifndef ProjectRoot
  #error ProjectRoot must be passed with /DProjectRoot=<path>
#endif

#ifndef Architecture
  #define Architecture "x86_64"
#endif

#define AppName "LM Studio Tray Manager"
#define AppPublisher "Ajimaru"
#define AppURL "https://github.com/Ajimaru/LM-Studio-Tray-Manager"
#define AppExeName "lmstudio-tray-manager.exe"

[Setup]
; A fixed GUID is what lets an upgrade replace the previous install rather
; than sitting beside it in Programs and Features. Never regenerate it.
AppId={{7C3F2A94-6B18-4D5E-9A21-8E4F1C0D5B73}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile={#ProjectRoot}\LICENSE
OutputBaseFilename=lmstudio-tray-manager-{#AppVersion}-windows-{#Architecture}-setup
SetupIconFile={#ProjectRoot}\build\windows\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; The tray is a per-user application: it writes its config under %APPDATA%
; and registers autostart in the user's Startup folder. lowest keeps the
; installer from demanding elevation it has no use for.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "autostart"; \
    Description: "{cm:AutoStartProgram,{#AppName}}"; \
    GroupDescription: "{cm:AdditionalIcons}"; \
    Flags: unchecked
Name: "desktopicon"; \
    Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; \
    Flags: unchecked

[Files]
Source: "{#ProjectRoot}\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\lmstudio_autostart.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\VERSION"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\AUTHORS"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; The tray holds no lock on its own files, but leaving a stale icon in the
; notification area after an uninstall looks like a failed removal.
Filename: "{sys}\taskkill.exe"; \
    Parameters: "/IM {#AppExeName} /F"; \
    Flags: runhidden; \
    RunOnceId: "StopTray"

[UninstallDelete]
; Logs are written next to the executable when that directory is writable,
; so they would otherwise be left behind in Program Files.
Type: filesandordirs; Name: "{app}\.logs"

[Messages]
english.WelcomeLabel2=This will install [name/ver] on your computer.%n%nLM Studio Tray Manager shows the status of the LM Studio daemon and desktop app in the notification area, and lets you start and stop both.
german.WelcomeLabel2=[name/ver] wird auf Ihrem Computer installiert.%n%nDer LM Studio Tray Manager zeigt den Status von LM-Studio-Daemon und Desktop-App im Infobereich an und erlaubt, beide zu starten und zu stoppen.
