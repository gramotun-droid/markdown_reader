; Inno Setup script for MD Reader.
; Packages the PyInstaller one-folder build (dist\MdReader) into a single
; lightweight Windows installer with Start Menu shortcut and uninstaller.
;
; Build locally:  iscc installer\mdreader.iss
; Versioned:      iscc /DMyAppVersion=1.0.0 installer\mdreader.iss

#ifndef MyAppVersion
#define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName "MD Reader"
#define MyAppPublisher "gramotun"
#define MyAppURL "https://github.com/gramotun-droid/markdown_reader"
#define MyAppExeName "MdReader.exe"

[Setup]
AppId={{209A8A9A-5908-4D2E-BA40-E280D3D0083F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\MdReader
DefaultGroupName=MD Reader
DisableProgramGroupPage=yes
; Resolve all relative paths (icon, dist\MdReader, OutputDir) from the repo
; root, since this script lives in installer\.
SourceDir=..
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer_output
OutputBaseFilename=MdReader-Setup
SetupIconFile=app\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\MdReader\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\MD Reader"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,MD Reader}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MD Reader"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,MD Reader}"; Flags: nowait postinstall skipifsilent
