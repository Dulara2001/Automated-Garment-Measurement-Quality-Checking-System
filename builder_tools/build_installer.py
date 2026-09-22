"""
GarmentQC AI - Step 2: Secure Installer Packer
-----------------------------------------------------------
1. SETUP: Enforces Visible Setup Key (NCG-AI-2026) via UserInfoPage.
2. DRIVERS: Bundles 'UnityCapture-master' files and auto-registers them.
3. COMPILER: Runs Inno Setup Compiler safely.
4. DEVICE CONFIG: Prompts user for a Device ID and saves it securely to the local data directory.
"""
import os
import sys
import subprocess
import time
from pathlib import Path

class SecureInstallerPacker:
    def __init__(self):
        # Adjusted to point to the parent directory (main project root)
        self.root = Path(__file__).parent.parent.absolute()
        self.dist_dir = self.root / "dist"
        self.output_dir = self.root / "installer_output"
        
        # --- CONFIGURATION (Must match build_app.py) ---
        self.app_name = "GarmentQC_AI"
        self.version = "2.0.5"
        self.setup_password = "NCG-AI-2026"  # Universal Setup Key
        self.unity_source_dir = self.root / "UnityCapture-master" / "Install"

    def compile_installer(self):
        print("="*60 + "\n   GarmentQC AI - INSTALLER PACKER (STEP 2) v" + self.version + "\n" + "="*60)
        
        if not (self.dist_dir / self.app_name).exists():
            print(f"\n[ERROR] App directory not found in 'dist/{self.app_name}'.")
            print("Please run 'build_app.py' first!")
            return False

        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        inno_paths = [
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", 
            r"C:\Program Files\Inno Setup 6\ISCC.exe",
            os.path.expanduser("~") + r"\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
        ]
        iscc = next((p for p in inno_paths if os.path.exists(p)), None)
        
        if not iscc:
            print("\n[WARN] Inno Setup not found. Cannot create .exe installer.")
            return False

        # --- UNITY CAPTURE ---
        has_unity = (self.unity_source_dir / "Install.bat").exists()
        unity_files_section = ""
        unity_run_section = ""
        
        if has_unity:
            print("[OK] Unity Capture drivers found. Adding to installer.")
            unity_files_section = f'Source: "UnityCapture-master\\Install\\*"; DestDir: "{{app}}\\UnityCapture"; Flags: ignoreversion recursesubdirs createallsubdirs'
            unity_run_section = f'Filename: "{{app}}\\UnityCapture\\Install.bat"; Parameters: ""; StatusMsg: "Registering Virtual Camera Drivers..."; Flags: runhidden waituntilterminated'
        else:
            print("[WARN] Unity Capture drivers NOT found. Skipping driver integration.")

        # --- INNO SCRIPT ---
        print("[*] Generating Installer Script...")
        script = f'''; Secure Installer Script
[Setup]
AppId={{{{B8F3C4D5-9E2A-4F7B-8A3C-1D6E5F9A2B7C}}}}
AppName={self.app_name}
AppVersion={self.version}
DefaultDirName={{autopf}}\\{self.app_name}
DefaultGroupName={self.app_name}
OutputDir={self.output_dir}
OutputBaseFilename={self.app_name}_Secure_Setup_v{self.version}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile={self.root}\\icon.ico
DisableProgramGroupPage=yes
PrivilegesRequired=admin

; --- USER INFO PAGE (VISIBLE KEY) ---
UserInfoPage=yes
UsePreviousAppDir=no
DisableDirPage=no

[Dirs]
Name: "{{app}}"; Permissions: users-full
Name: "{{app}}\\data"; Permissions: users-full

[Files]
Source: "dist\\{self.app_name}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
{unity_files_section}

[Icons]
Name: "{{autodesktop}}\\{self.app_name}"; Filename: "{{app}}\\Launch_GarmentQC.bat"; IconFilename: "{{app}}\\{self.app_name}.exe"; IconIndex: 0
Name: "{{group}}\\{self.app_name}"; Filename: "{{app}}\\Launch_GarmentQC.bat"; IconFilename: "{{app}}\\{self.app_name}.exe"; IconIndex: 0

[Run]
{unity_run_section}
Filename: "{{app}}\\Launch_GarmentQC.bat"; Description: "Launch {self.app_name}"; Flags: postinstall nowait skipifsilent

[Code]
var
  DeviceIDPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  // Create the Device ID Input Page
  DeviceIDPage := CreateInputQueryPage(wpUserInfo,
    'Device Configuration', 'Device ID Setup',
    'Please enter the unique Device ID for this machine. This ID will be attached to all QC reports sent to the database.');
  DeviceIDPage.Add('Device ID:', False);
  DeviceIDPage.Values[0] := 'QC-STATION-01'; // Default value
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigStr: String;
begin
  // Save the Device ID to a JSON file after installation is complete
  if CurStep = ssPostInstall then
  begin
    // Write out the configuration using properly escaped curly brackets
    ConfigStr := '{{ "device_id": "' + DeviceIDPage.Values[0] + '" }}';
    SaveStringToFile(ExpandConstant('{{app}}\\data\\device_config.json'), ConfigStr, False);
  end;
end;

function CheckSerial(Serial: String): Boolean;
begin
  Result := Serial = '{self.setup_password}';
end;
'''
        script_file = self.root / "installer.iss"
        script_file.write_text(script, encoding='utf-8-sig')
        
        # --- RUN COMPILER ---
        max_retries = 3
        for attempt in range(max_retries):
            print(f"[*] Running Inno Setup Compiler (Attempt {attempt+1}/{max_retries})...")
            result = subprocess.run([iscc, str(script_file)], capture_output=True, text=True)
            
            if result.returncode == 0:
                print("\n" + "="*60 + "\n   INSTALLER CREATED SUCCESSFULLY!\n" + "="*60)
                print(f"   Output: {self.output_dir}\\{self.app_name}_Secure_Setup_v{self.version}.exe")
                print(f"   Setup Password: {self.setup_password}")
                return True
            
            if "EndUpdateResource" in result.stderr or "MoveFile" in result.stderr:
                print(f"    [WARN] Antivirus locked the output file. Retrying in 3 seconds...")
                time.sleep(3)
            else:
                print("\n[ERROR] Inno Setup Failed!")
                print(result.stderr)
                return False
        
        print("\n[ERROR] Could not build installer after retries. Please disable Antivirus temporarily.")
        return False

if __name__ == "__main__":
    SecureInstallerPacker().compile_installer()