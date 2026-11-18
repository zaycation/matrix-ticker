; Inno Setup script: builds MatrixTicker-Setup-<version>.exe from the PyInstaller output.
; Built by .github/workflows/build.yml (ISCC.exe /DAppVersion=x.y.z packaging\installer.iss)

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{6C1E1F2A-7B54-4C8E-9C2F-4F0D7A3B9E11}
AppName=Matrix Ticker
AppVersion={#AppVersion}
AppPublisher=zaycation
AppPublisherURL=https://github.com/zaycation/matrix-ticker
AppSupportURL=https://github.com/zaycation/matrix-ticker/issues
DefaultDirName={autopf}\Matrix Ticker
DefaultGroupName=Matrix Ticker
DisableProgramGroupPage=yes
; Per-user install: no admin prompt.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=MatrixTicker-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\MatrixTicker.exe
UninstallDisplayName=Matrix Ticker
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Close a running copy before installing/updating or uninstalling.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Matrix Ticker when &Windows starts (in the system tray)"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\MatrixTicker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Matrix Ticker"; Filename: "{app}\MatrixTicker.exe"
Name: "{autodesktop}\Matrix Ticker"; Filename: "{app}\MatrixTicker.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "MatrixTicker"; ValueData: """{app}\MatrixTicker.exe"" --tray"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\MatrixTicker.exe"; Description: "Launch Matrix Ticker"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM MatrixTicker.exe /F"; Flags: runhidden; RunOnceId: "KillApp"
