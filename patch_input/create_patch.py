"""
GarmentQC AI - LIGHTWEIGHT PATCH GENERATOR
-------------------------------------------------------
1. Keep this script INSIDE your 'patch_input' folder.
2. Copy ONLY your changed, compiled files (like GarmentQC_AI.exe or the system/libs folder) into this 'patch_input' folder.
3. Run the script. It will automatically ignore itself, package the small update, and merge it with your master manifest.
"""
import os
import json
import hashlib
import shutil
import time
from pathlib import Path

# --- CONFIGURATION (MUST MATCH UPDATER.PY & BUILDER) ---
ENCRYPTION_KEY = b"REDACTED_ROTATED_KEY" 
MODEL_XOR_KEY = 42                       

# --- DYNAMIC PATH RESOLUTION ---
# Since this script is INSIDE 'patch_input', the input dir is the folder it sits in.
INPUT_DIR = Path(__file__).parent.absolute()

# The output dir is one folder up (the main project folder) -> server_upload
ROOT_DIR = INPUT_DIR.parent
OUTPUT_DIR = ROOT_DIR / "server_upload"
VERSION_FILE_NAME = "sys_config_v1.bin"

# Special Mapping: Forces specific files to hidden system paths
SPECIAL_PATHS = {
    "fashion_landmark.onnx": ("system/libs/sys_core_v1.dll", True),
    "fashion_landmark.onnx.data": ("system/libs/sys_core_v1.dll.data", True)
}

def xor_encrypt(data, key):
    """Encrypts data using XOR based on key type."""
    if isinstance(key, int):
        return bytearray(b ^ key for b in data)
    else:
        key_len = len(key)
        return bytearray(b ^ key[i % key_len] for i, b in enumerate(data))

def generate_patch():
    print("="*60)
    print("   GarmentQC AI - LIGHTWEIGHT PATCH GENERATOR")
    print("="*60)

    print("\nEnter New Patch Version (e.g., 1.0.5):")
    ver = input("Version: ").strip()
    if not ver: return

    # --- SETUP OUTPUT DIRECTORIES ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    version_dir = OUTPUT_DIR / f"v{ver}"
    if version_dir.exists():
        try: shutil.rmtree(version_dir)
        except: pass
    version_dir.mkdir(exist_ok=True)

    # --- 1. LOAD THE MASTER MANIFEST ---
    # Strictly looks for release.json INSIDE the server_upload folder
    manifest_path = OUTPUT_DIR / "release.json"
    manifest = {"version": ver, "files": {}}
    
    if manifest_path.exists():
        try:
            with open(manifest_path, "r") as f:
                old_data = json.load(f)
                # KEEP all old files in the manifest! 
                # This ensures the client knows about files we aren't updating right now.
                manifest["files"] = old_data.get("files", {})
                print(f"[OK] Found existing release.json in {OUTPUT_DIR.name}. Merging lightweight update...")
        except Exception as e:
            print(f"[ERROR] Could not read release.json: {e}")
            return
    else:
        print(f"[WARNING] No release.json found in '{OUTPUT_DIR.name}' folder!")
        print("If this is your first update, this is normal. Otherwise, ensure you didn't delete server_upload.")
        time.sleep(2)

    manifest["version"] = ver
    files_processed = 0

    # --- 2. PROCESS ONLY FILES INSIDE 'patch_input' ---
    print(f"\n[Encrypting Changed Files in '{INPUT_DIR.name}/'...]")
    
    for file_path in INPUT_DIR.rglob("*"):
        if not file_path.is_file(): continue
        
        # CRITICAL SAFETY: Ignore this patch script itself so it doesn't get uploaded!
        if file_path.name == "create_patch.py": continue

        try:
            content = file_path.read_bytes()
        except Exception as e:
            print(f"    [ERROR] Could not read {file_path.name}: {e}")
            continue

        # Path is calculated relative to 'patch_input'
        rel_path = file_path.relative_to(INPUT_DIR).as_posix()
        
        # --- SECURITY LAYER 1: Model Obfuscation ---
        if file_path.name in SPECIAL_PATHS:
            target_path, do_obfuscate = SPECIAL_PATHS[file_path.name]
            rel_path = target_path
            if do_obfuscate:
                print(f"    [SECURE] Obfuscating Model: {file_path.name} -> {target_path}")
                content = xor_encrypt(content, MODEL_XOR_KEY)

        # --- SECURITY LAYER 2: Transport Encryption ---
        f_hash = hashlib.md5(content).hexdigest()
        transport_data = xor_encrypt(content, ENCRYPTION_KEY)
        
        # Save to the specific VERSION folder
        bin_name = f"{f_hash}.bin"
        (version_dir / bin_name).write_bytes(transport_data)

        # OVERWRITE or ADD this specific file's hash and URL into the master manifest
        # This leaves all the other unchanged files perfectly intact in the JSON!
        manifest["files"][rel_path] = {
            "hash": f_hash,
            "url": f"v{ver}/{bin_name}" 
        }
        
        print(f"    [PACKED] {rel_path} -> v{ver}/{bin_name}")
        files_processed += 1

    if files_processed == 0:
        print(f"\n[!] No files found to pack (ignored create_patch.py).")
        return

    # --- 3. SAVE OUTPUTS TO SERVER_UPLOAD ---
    (OUTPUT_DIR / "release.json").write_text(json.dumps(manifest, indent=4))
    
    version_data = json.dumps({"version": ver}).encode('utf-8')
    encrypted_version = xor_encrypt(version_data, ENCRYPTION_KEY)
    (OUTPUT_DIR / VERSION_FILE_NAME).write_bytes(encrypted_version)

    print("-" * 60)
    print(f"LIGHTWEIGHT PATCH v{ver} READY.")
    print(f"Files Processed: {files_processed}")
    print("-" * 60)
    print(f"INSTRUCTIONS:")
    print(f"1. Open the '{OUTPUT_DIR.name}' folder.")
    print(f"2. Upload the new 'v{ver}' folder, 'release.json', and '{VERSION_FILE_NAME}' to your server.")
    print("="*60)
    time.sleep(2)

if __name__ == "__main__":
    generate_patch()