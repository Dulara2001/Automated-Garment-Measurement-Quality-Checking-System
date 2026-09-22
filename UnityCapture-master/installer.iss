; Secure Installer Script
[Setup]
AppId={B8F3C4D5-9E2A-4F7B-8A3C-1D6E5F9A2B7C}
AppName=GarmentQC AI Pro
AppVersion=1.0.0
DefaultDirName={autopf}\GarmentQC_AI
DefaultGroupName=GarmentQC AI
OutputDir=d:\Emmanuels_Lanka\Size_Measure_Project\back\new host back\GarmentQC_App copy-3\installer_output
OutputBaseFilename=GarmentQC_AI_Secure_Setup_v1.0.0
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=d:\Emmanuels_Lanka\Size_Measure_Project\back\new host back\GarmentQC_App copy-3\icon.ico
UserInfoPage=yes
DisableDirPage=no
CloseApplications=yes
RestartApplications=no
PrivilegesRequired=admin

[Dirs]
Name: "{app}"; Permissions: users-full

[Files]
; Main App Files
Source: "dist\GarmentQC_AI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Unity Capture Driver Files
Source: "UnityCapture-master\Install\*"; DestDir: "{app}\UnityCapture"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GarmentQC AI"; Filename: "{app}\Launch_GarmentQC.bat"; IconFilename: "{app}\GarmentQC_AI.exe"; IconIndex: 0
Name: "{autodesktop}\GarmentQC AI"; Filename: "{app}\Launch_GarmentQC.bat"; IconFilename: "{app}\GarmentQC_AI.exe"; IconIndex: 0

[Run]
; Install Drivers First
Filename: "{app}\UnityCapture\Install.bat"; Parameters: ""; StatusMsg: "Registering Virtual Camera Drivers..."; Flags: runhidden waituntilterminated
; Then Launch App
Filename: "{app}\Launch_GarmentQC.bat"; Description: "Launch GarmentQC AI"; Flags: postinstall nowait skipifsilent

[Code]
function CheckSerial(Serial: String): Boolean;
begin
  Result := Serial = 'NCG-AI-2026';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpUserInfo then begin
    // FIXED: Use WizardForm.UserInfoSerialEdit.Text
    if not CheckSerial(WizardForm.UserInfoSerialEdit.Text) then begin
      MsgBox('Invalid License Key!', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
