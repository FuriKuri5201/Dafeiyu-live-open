; Inno Setup Script for 鲶鱼大帝之大肥鱼一键开播助手
; Run build_release.ps1 first to generate dist\DFYZB-Open\, then compile this script in Inno Setup.

[Setup]
AppName=鲶鱼大帝之大肥鱼一键开播助手
AppVersion=1.0.0
AppPublisher=FuriKuri5201
DefaultDirName={autopf}\DFYZB-Open
DefaultGroupName=鲶鱼大帝之大肥鱼一键开播助手
OutputDir=dist
OutputBaseFilename=DFYZB-OneClick-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"

[Files]
Source: "dist\DFYZB-Open\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\鲶鱼大帝之大肥鱼一键开播助手"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "app.py"; WorkingDir: "{app}"
Name: "{autodesktop}\大肥鱼一键开播助手"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "app.py"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: "app.py"; WorkingDir: "{app}"; Description: "立即启动大肥鱼一键开播助手"; Flags: nowait postinstall skipifsilent
