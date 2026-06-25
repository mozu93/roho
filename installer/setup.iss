; installer/setup.iss
#define MyAppName "労働保険名簿管理システム"
#define MyAppExeName "Rouho.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyOutputBase "Rouho_Setup"

[Setup]
AppId={{F3A2B1C4-8D5E-4F6A-9B3C-2E7D1F0A8C5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=労働保険事務組合
DefaultDirName={localappdata}\Rouho
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\installer_output
OutputBaseFilename={#MyOutputBase}_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成"; GroupDescription: "追加タスク:"

[Files]
Source: "..\dist\Rouho\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "アプリを起動する"; Flags: nowait postinstall skipifsilent
