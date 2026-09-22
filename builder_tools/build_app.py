"""
GarmentQC AI - Step 1: Secure App Builder
-----------------------------------------------------------
1. AUTO-ENV: Bundles Python + Libraries into one EXE.
2. SECURITY: Encrypts .onnx -> fake .dll files (XOR).
3. GARBAGE: Generates massive decoy files (2000+) to confuse reverse engineers.
"""
import os
import sys
import shutil
import subprocess
import time
import random
import string
import json
from pathlib import Path

# --- SECURITY KEY (Must match inference.py / windows_test.py logic) ---
MODEL_XOR_KEY = 42

class SecureAppBuilder:
    def __init__(self):
        # Adjusted to point to the parent directory (main project root)
        self.root = Path(__file__).parent.parent.absolute()
        self.build_dir = self.root / "build"
        self.dist_dir = self.root / "dist"
        
        # --- CONFIGURATION ---
        self.app_name = "GarmentQC_AI"
        self.main_script = "windows_test.py" 
        self.version = "2.0.0"
        
    def print_step(self, step, total, text):
        print(f"\n[{step}/{total}] {text}")

    def clean_build(self):
        self.print_step(1, 7, "Cleaning workspace...")
        for i in range(3):
            try:
                if self.build_dir.exists(): shutil.rmtree(self.build_dir)
                if self.dist_dir.exists(): shutil.rmtree(self.dist_dir)
                break
            except Exception as e:
                print(f"    [!] Files locked ({e}). Retrying in 2s...")
                time.sleep(2)

    def verify_files(self):
        self.print_step(2, 7, "Verifying source files...")
        if not os.environ.get("GARMENT_QC_ENCRYPTION_KEY"):
            print("\n[ERROR] GARMENT_QC_ENCRYPTION_KEY env var is not set. Set it before building.")
            sys.exit(1)
        required = [
            self.main_script, "models/fashion_landmark.onnx", "icon.ico", 
            "updater.py", "web_launcher.py", "security/activator.py", 
            "security/secure_config.py", "security/license_guard.py"
        ]
        missing = [f for f in required if not (self.root / f).exists()]
        
        if not (self.root / "loading").exists():
             print("\n[ERROR] Missing 'loading' folder! Splash screen needs this.")
             sys.exit(1)

        if missing:
            print("\n[ERROR] CRITICAL ERROR: Missing files!")
            for f in missing: print(f"    - {f}")
            sys.exit(1)
            
        print("    [OK] All core files found!")

    def create_spec(self):
        self.print_step(3, 7, "Creating build config...")
        static_src = str(self.root / 'static').replace('\\', '\\\\')
        icon_path = str(self.root / 'icon.ico').replace('\\', '\\\\')
        
        # ---> SECURE FIX: Dynamically grab ALL images (slide1, slide2, etc.) but ignore .py files <---
        loading_dir = self.root / 'loading'
        image_tuples = []
        if loading_dir.exists():
            for ext in ['*.png', '*.jpg', '*.jpeg']:
                for img_path in loading_dir.glob(ext):
                    safe_path = str(img_path).replace('\\', '\\\\')
                    image_tuples.append(f"('{safe_path}', 'loading')")
                    
        image_tuples_str = ",\n    ".join(image_tuples)
        # -----------------------------------------------------------------------------------------

        spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata, collect_dynamic_libs

# ---> THE NUCLEAR OPTION: FORCE GATHER ALL REMBG DEPENDENCIES <---
rembg_hidden = (
    collect_submodules('rembg') + 
    collect_submodules('pymatting') + 
    collect_submodules('pooch') + 
    collect_submodules('scipy') + 
    collect_submodules('skimage')
)

rembg_datas = (
    collect_data_files('rembg') + 
    copy_metadata('rembg') + 
    copy_metadata('pooch') + 
    copy_metadata('pymatting') + 
    copy_metadata('onnxruntime') + 
    copy_metadata('scipy') + 
    copy_metadata('scikit-image') +
    copy_metadata('pillow') +
    copy_metadata('numpy') +
    collect_dynamic_libs('onnxruntime') 
)

block_cipher = None

# ---> SECURE FILE LIST: Only the explicitly found images are copied as raw data <---
added_files = [
    ('{static_src}', 'static'),
    {image_tuples_str + ',' if image_tuples_str else ''}
] + rembg_datas

hidden_imports = [
    'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
    'fastapi', 'starlette', 'pydantic',
    'cv2', 'numpy', 'onnxruntime', 'multipart', 'python-multipart', 
    'engineio.async_drivers.threading', 
    'webview', 'clr', 'System', 'requests', 'threading', 'subprocess', 
    'updater', 'loading.splash_theme', 'web_launcher',
    'supabase', 'gotrue', 'postgrest', 'storage3', 'realtime',
    'cryptography', 'boto3', 'botocore',
    'security.activator', 'security.license_guard', 'security.secure_config',
] + rembg_hidden

a = Analysis(
    ['{self.main_script}'],
    pathex=['{str(self.root).replace('\\', '\\\\')}'], 
    binaries=[], datas=added_files, hiddenimports=hidden_imports,
    hookspath=[], hooksconfig={{}}, runtime_hooks=[],
    excludes=['pandas', 'tkinter', 'IPython'],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='{self.app_name}', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=True, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None,
    entitlements_file=None, icon='{icon_path}', uac_admin=True
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=True,
    upx_exclude=[], name='{self.app_name}',
)
'''
        spec_file = self.root / f"{self.app_name}.spec"
        spec_file.write_text(spec_content, encoding="utf-8")
        return spec_file

    def build_exe(self, spec_file):
        self.print_step(4, 7, "Compiling App (Bundling Libs)...")
        cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_file)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("\n[ERROR] PYINSTALLER FAILED!")
            print('\n'.join(result.stderr.splitlines()[-20:]))
            sys.exit(1)
        print("    [OK] App compiled successfully!")

    def _encrypt_and_copy(self, src, dst):
        if not src.exists(): return
        print(f"    [ENCRYPTING] {src.name} -> {dst.name}")
        with open(src, "rb") as f_in: data = bytearray(f_in.read())
        for i in range(len(data)): data[i] ^= MODEL_XOR_KEY
        with open(dst, "wb") as f_out: f_out.write(data)

    def secure_post_process(self):
        self.print_step(5, 7, "Encrypting Assets & Adding Massive Garbage...")
        dist_app_dir = self.dist_dir / self.app_name
        
        rogue_models_dir = dist_app_dir / "models"
        if rogue_models_dir.exists():
            shutil.rmtree(rogue_models_dir)
            print("    [SECURE] Leaked plain models deleted.")
        
        hidden_lib_dir = dist_app_dir / "system" / "libs"
        hidden_lib_dir.mkdir(parents=True, exist_ok=True)
        self._encrypt_and_copy(self.root / "models" / "fashion_landmark.onnx", hidden_lib_dir / "sys_core_v1.dll")
        self._encrypt_and_copy(self.root / "models" / "fashion_landmark.onnx.data", hidden_lib_dir / "sys_core_v1.dll.data")

        # ---> Disguise u2net without encryption (Fast Load) <---
        src_u2net = self.root / "models" / "u2net.onnx"
        dst_u2net = hidden_lib_dir / "sys_bg_v1.dll"
        if src_u2net.exists():
            print(f"    [DISGUISING] {src_u2net.name} -> {dst_u2net.name} (Unencrypted)")
            shutil.copy2(src_u2net, dst_u2net)
        # -----------------------------------------------------------

        fake_structure = [
            "cache/gpu_v1", "cache/gpu_v2", "logs/sys/dump", "logs/net/history",
            "drivers/x86", "drivers/legacy", "temp/dmp", "temp/pre-fetch",
            "bin/resources/libs", "bin/assets/textures", "data/backup/auto",
            "sys_config/recovery", "update/temp", "_internal/plugins",
            "_internal/node_modules/core", "lib/site-packages/numpy/core"
        ]
        
        file_extensions = [".dll", ".tmp", ".dat", ".cache", ".bin", ".log", ".pak"]
        for fd in fake_structure:
            p = dist_app_dir / fd
            p.mkdir(parents=True, exist_ok=True)
            for _ in range(random.randint(60, 100)):
                ext = random.choice(file_extensions)
                fname = "sys_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)) + ext
                (p / fname).write_bytes(os.urandom(random.randint(1024, 20480)))
        print("    [SECURE] Garbage injection complete.")

    def create_config(self):
        self.print_step(6, 7, "Preparing folder structure & encrypting version...")
        data_dir = self.dist_dir / self.app_name / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "reports").mkdir(exist_ok=True)
        (data_dir / "references").mkdir(exist_ok=True)
        (data_dir / "pending_uploads").mkdir(exist_ok=True)

        enc_key = os.environ.get("GARMENT_QC_ENCRYPTION_KEY", "").encode()
        if not enc_key:
            print("\n[ERROR] GARMENT_QC_ENCRYPTION_KEY env var is not set. Cannot encrypt version file.")
            sys.exit(1)
        version_data = json.dumps({"version": self.version}).encode('utf-8')
        encrypted_version = bytearray(b ^ enc_key[i % len(enc_key)] for i, b in enumerate(version_data))
        (self.dist_dir / self.app_name / "sys_config_v1.bin").write_bytes(encrypted_version)

    def create_launcher(self):
        self.print_step(7, 7, "Creating launcher script...")
        enc_key = os.environ.get("GARMENT_QC_ENCRYPTION_KEY", "")
        # Baked into the built launcher only (dist/ is not committed to git), so the
        # shipped EXE can read the same key at runtime via the environment.
        launcher_content = f'''@echo off\ntitle GarmentQC AI - Pro\ncolor 0B\ncd /d "%~dp0"\nset "GARMENT_QC_ENCRYPTION_KEY={enc_key}"\nif not exist "data" mkdir data\\reports data\\references data\\pending_uploads\nstart "" "{self.app_name}.exe"\n'''
        (self.dist_dir / self.app_name / "Launch_GarmentQC.bat").write_text(launcher_content, encoding="utf-8")

    def build(self):
        print("="*60 + "\n   GarmentQC AI - APP BUILDER (STEP 1) v" + self.version + "\n" + "="*60)
        try:
            self.clean_build()
            self.verify_files()
            self.build_exe(self.create_spec())
            self.secure_post_process() 
            self.create_config()
            self.create_launcher() 
            print("\n" + "="*60 + "\n   APP BUILD COMPLETE! Ready for testing or installer packing.\n" + "="*60)
        except Exception as e:
            print(f"\n[FATAL] ERROR: {e}")

if __name__ == "__main__":
    SecureAppBuilder().build()