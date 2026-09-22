
import os
import sys
import requests
import hashlib
import json
import subprocess
import shutil
import zipfile
import time
from threading import Thread

# --- GITHUB CONFIGURATION ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_OWNER = "wpslakshitha"
REPO_NAME = "garment-qc-updates"

VERSION_FILE = "sys_config_v1.bin" # The encrypted version file
ENCRYPTION_KEY = os.environ.get("GARMENT_QC_ENCRYPTION_KEY", "").encode()

def xor_crypt(data):
    """Decrypts (or encrypts) data back to original."""
    if not ENCRYPTION_KEY:
        raise RuntimeError("GARMENT_QC_ENCRYPTION_KEY env var is not set")
    key_len = len(ENCRYPTION_KEY)
    return bytearray(b ^ ENCRYPTION_KEY[i % key_len] for i, b in enumerate(data))

# Alias for backwards compatibility
xor_decrypt = xor_crypt

def check_for_updates(ask_user_callback=None, on_status=None, on_progress=None, run_in_background=False):
    """
    Main update function with progress tracking.
    If run_in_background is False (Default), it blocks the script (used for startup).
    If run_in_background is True, it runs in a thread (used for in-app manual updates).
    """
    def log(msg):
        print(f"[Updater] {msg}")
        if on_status: on_status(msg)

    def _run_update_logic():
        try:
            # 1. Hit the GitHub API for the latest release
            api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            
            try:
                r = requests.get(api_url, headers=headers, timeout=10)
                if r.status_code != 200: 
                    log(f"Failed to fetch latest release. (Code: {r.status_code})")
                    return
                release_data = r.json()
            except Exception as e:
                log(f"Connection error: {e}")
                return

            # 2. Check Version Tag
            latest_version_tag = release_data.get("tag_name", "v0.0.0") # e.g., v2.0.1
            latest_clean = latest_version_tag.replace("v", "")
            
            local_clean = "0.0.0"
            if os.path.exists(VERSION_FILE):
                try:
                    with open(VERSION_FILE, "rb") as f:
                        decrypted_data = xor_crypt(f.read())
                        local_clean = json.loads(decrypted_data.decode('utf-8')).get("version", "0.0.0")
                except: 
                    pass

            if latest_clean == local_clean:
                log(f"App is up to date (v{local_clean}).")
                return 

            log(f"New Update Found: v{latest_clean} (Current: v{local_clean})")

            # --- INTERACTIVE LOGIC ---
            if ask_user_callback:
                should_update = ask_user_callback(latest_version_tag)
                if not should_update:
                    log("User skipped the update.")
                    return
            # ------------------------------

            # 3. Find the patch.zip asset in the release
            assets = release_data.get("assets", [])
            download_url = None
            for asset in assets:
                if asset["name"].endswith(".zip"):
                    download_url = asset["url"]
                    break
            
            if not download_url:
                log("No .zip patch file found in the latest GitHub release.")
                return

            # Prepare Cache Directory
            cache_dir = os.path.join(os.getcwd(), "update_cache")
            if os.path.exists(cache_dir): shutil.rmtree(cache_dir, ignore_errors=True)
            os.makedirs(cache_dir)

            zip_path = os.path.join(cache_dir, "patch.zip")

            # 4. Download the Asset WITH PROGRESS TRACKING
            log("Downloading patch files from GitHub...")
            download_headers = {
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/octet-stream"
            }
            
            with requests.get(download_url, headers=download_headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                
                # Get total file size from GitHub Headers
                total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0
                
                with open(zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            
                            # Calculate percentage and trigger UI update
                            if total_size > 0 and on_progress:
                                percent = int((downloaded_size / total_size) * 100)
                                on_progress(percent)

            # 5. Extract the ZIP file
            log("Extracting and decrypting files...")
            extract_dir = os.path.join(cache_dir, "extracted")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            os.remove(zip_path) # Clean up the zip

            # Find release.json (in case it was zipped inside a folder)
            manifest_path = os.path.join(extract_dir, "release.json")
            if not os.path.exists(manifest_path):
                for root, dirs, files in os.walk(extract_dir):
                    if "release.json" in files:
                        extract_dir = root
                        manifest_path = os.path.join(root, "release.json")
                        break
            
            if not os.path.exists(manifest_path):
                 log("Error: release.json not found in the downloaded zip.")
                 return

            # 6. Read Manifest and Decrypt files
            with open(manifest_path, "r") as f:
                manifest = json.load(f)

            ready_dir = os.path.join(cache_dir, "ready_to_apply")
            os.makedirs(ready_dir, exist_ok=True)

            for rel_path, info in manifest.get("files", {}).items():
                bin_path = os.path.join(extract_dir, info["url"])
                
                if os.path.exists(bin_path):
                    with open(bin_path, "rb") as f:
                        encrypted_content = f.read()

                    decrypted_content = xor_decrypt(encrypted_content)

                    # Verify hash security
                    if hashlib.md5(decrypted_content).hexdigest() == info["hash"]:
                        target_disk_path = os.path.join(ready_dir, rel_path)
                        os.makedirs(os.path.dirname(target_disk_path), exist_ok=True)
                        with open(target_disk_path, "wb") as f:
                            f.write(decrypted_content)
                    else:
                        log(f"Security Alert: Hash mismatch for {rel_path}")

            # Also copy the new version file to be applied
            sys_config_path = os.path.join(extract_dir, "sys_config_v1.bin")
            if os.path.exists(sys_config_path):
                shutil.copy2(sys_config_path, os.path.join(ready_dir, "sys_config_v1.bin"))

            # 7. Apply Update (Using Batch Script)
            log("Applying update and restarting...")
            batch_script = f"""
@echo off
title Updating GarmentQC AI...
echo Waiting for application to close...
timeout /t 2 /nobreak > nul

echo Killing Process if running...
taskkill /F /IM GarmentQC_AI.exe >nul 2>&1

echo Copying new files...
xcopy /s /y /e "{ready_dir}\\*" "."

echo Cleaning up cache...
rmdir /s /q "{cache_dir}"

echo Restarting Application...
start "" "GarmentQC_AI.exe"

echo Update Complete.
del "%~f0"
"""
            with open("apply_patch.bat", "w") as f:
                f.write(batch_script)

            subprocess.Popen(["apply_patch.bat"], shell=True)
            os._exit(0)

        except Exception as e:
            log(f"Update Error: {e}")

    # --- DUAL MODE EXECUTION ---
    if run_in_background:
        # For triggering from inside the app UI
        Thread(target=_run_update_logic, daemon=True).start()
    else:
        # For blocking during the startup splash screen
        _run_update_logic()

# --- BACKWARDS COMPATIBILITY ---
check_for_updates_silently = check_for_updates