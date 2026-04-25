; Version is overridden by: iscc /DMyAppVersion=0.16.4 metis_installer.iss
; Default must match metis_version.py (METIS_VERSION).
#ifndef MyAppVersion
  #define MyAppVersion "0.16.4"
#endif
#define MyAppName "Metis Command"
#define MyAppPublisher "Metis Team"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Metis Command
DefaultGroupName=Metis Command
UninstallDisplayIcon={app}\Metis.exe
Compression=lzma2
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=Metis_Command_Setup
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=compiler:SetupClassicIcon.ico

[Files]
; The main standalone executable built by PyInstaller
Source: "dist\Metis.exe"; DestDir: "{app}"; Flags: ignoreversion

; Seed initial directories that the application might expect next to the executable
Source: "plugins\*"; DestDir: "{app}\plugins"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\Metis.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\Metis.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\Metis.exe"; Description: "Launch Metis Command"; Flags: nowait postinstall skipifsilent
