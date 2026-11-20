; Inno Setup script to package dist\OpenNotch.exe into OpenNotch-Setup.exe
[Setup]
AppName=OpenNotch
AppVersion=0.1.0
DefaultDirName={localappdata}\Programs\OpenNotch
DefaultGroupName=OpenNotch
OutputDir=dist
OutputBaseFilename=OpenNotch-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest

[Tasks]
Name: "autostart"; Description: "Start OpenNotch automatically when Windows starts"; GroupDescription: "Startup:"

[Files]
Source: "dist\OpenNotch.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\OpenNotch"; Filename: "{app}\OpenNotch.exe"
Name: "{autodesktop}\OpenNotch"; Filename: "{app}\OpenNotch.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "OpenNotch"; ValueData: """{app}\OpenNotch.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\OpenNotch.exe"; Description: "Launch OpenNotch"; Flags: nowait postinstall skipifsilent
