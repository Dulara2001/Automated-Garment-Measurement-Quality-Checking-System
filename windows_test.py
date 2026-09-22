# ==============================================================================
# GARMENT QC AI - MAIN APPLICATION
# Copyright (c) 2026 Namal Chamodya. All Rights Reserved.
# Developer: Namal Chamodya
# ==============================================================================

__author__ = "Namal Chamodya"
__copyright__ = "Copyright (c) 2026 Namal Chamodya"
__license__ = "Proprietary"

import cv2
import numpy as np
import json
import os
import sys
import copy
import threading
import time
import requests
import asyncio 
from datetime import datetime
from pathlib import Path
from typing import Optional

# --- FIX 1: HIGH DPI AWARENESS (Fixes Huge ROI Circle) ---
import ctypes
try:
    # Forces Windows to treat this app as "DPI Aware".
    # Prevents 125%/150% scaling from stretching the camera feed and circles.
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass # Not on Windows or older version

# --- PLATFORM CONFIG ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- IMPORTS ---
import web_launcher 
import updater
from camera_manager import CameraManager
from trouser_processor import TrouserProcessor
from shirt_processor import ShirtProcessor
from inference import ImageProcessor
from processing_engine import MeasurementEngine
from calibrator import Calibrator
from qc_validator import QCValidator
import garment_config
from sync_manager import CloudSyncManager
import wifi_manager
import uvicorn

# --- CONFIGURATION ---
HOST_WEB_URL = "https://qweb-flame.vercel.app" 

# --- LOGGING SETUP ---
if getattr(sys, 'frozen', False):
    log_path = Path(sys.executable).parent / "app_logs.txt"
    sys.stdout = open(log_path, "w", buffering=1)
    sys.stderr = open(log_path, "w", buffering=1)

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- PATH SETUP ---
# if getattr(sys, 'frozen', False):
#     # CRITICAL OTA FIX: Anchor the working directory to the .exe location
#     # This ensures apply_patch.bat knows exactly where to paste the files.
#     os.chdir(os.path.dirname(sys.executable))
    
#     BASE_DIR = Path(sys._MEIPASS)
#     PROJECT_ROOT = Path(os.path.dirname(sys.executable))
# else:
#     BASE_DIR = Path(__file__).parent
#     PROJECT_ROOT = BASE_DIR

# --- PATH SETUP ---
if getattr(sys, 'frozen', False):
    # CRITICAL OTA FIX: Anchor the working directory to the .exe location
    # This ensures apply_patch.bat knows exactly where to paste the files.
    os.chdir(os.path.dirname(sys.executable))
    
    BASE_DIR = Path(sys._MEIPASS)
    PROJECT_ROOT = Path(os.path.dirname(sys.executable))
    
    # ====================================================================
    # ---> CRITICAL FIX: SECURE SPLASH SCREEN LOADER <---
    # web_launcher looks for the 'loading' folder in the current directory.
    # We must extract it from PyInstaller's hidden folder and auto-decrypt.
    # ====================================================================
    import shutil
    hidden_loading_dir = BASE_DIR / "loading"
    visible_loading_dir = PROJECT_ROOT / "loading"
    
    if hidden_loading_dir.exists():
        visible_loading_dir.mkdir(parents=True, exist_ok=True)
        for file_path in hidden_loading_dir.iterdir():
            dest_path = visible_loading_dir / file_path.name
            
            # Check if it's an image file
            if file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.ico', '.gif']:
                try:
                    # Smart Check: Read the first byte to see if it is encrypted
                    with open(file_path, 'rb') as f:
                        first_byte = f.read(1)[0]
                        
                    # Standard unencrypted image starting bytes: 
                    # PNG = 137, JPG = 255, ICO = 0, GIF = 71
                    is_encrypted = first_byte not in [137, 255, 0, 71]
                    
                    if is_encrypted:
                        data = np.fromfile(str(file_path), dtype=np.uint8)
                        data ^= 42  # Apply your XOR decryption key
                        data.tofile(str(dest_path))
                    else:
                        shutil.copy2(file_path, dest_path)
                except Exception:
                    shutil.copy2(file_path, dest_path)
            else:
                # HTML, CSS, JS files copy normally
                shutil.copy2(file_path, dest_path)
    # ====================================================================
    
else:
    BASE_DIR = Path(__file__).parent
    PROJECT_ROOT = BASE_DIR

DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
REFERENCE_DIR = DATA_DIR / "references"
TEMP_DIR = DATA_DIR / "temp"
SIZE_STANDARDS_FILE = DATA_DIR / "size_standards.json"
CALIBRATION_FILE = DATA_DIR / "calibration.json"
DEVICE_CONFIG_FILE = DATA_DIR / "device_config.json"
LINE_CONFIG_FILE = DATA_DIR / "line_config.json"

# endpoints_server imports this module back (circular import) and mounts
# /static and /data at import time based on PROJECT_ROOT/DATA_DIR above, so
# it must be imported AFTER those are defined, or the mounts silently never
# register and every /static/* and /data/* request 404s.
import endpoints_server

for d in [REPORTS_DIR, REFERENCE_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

if not SIZE_STANDARDS_FILE.exists():
    with open(SIZE_STANDARDS_FILE, 'w') as f:
        json.dump(garment_config.SIZE_STANDARDS, f, indent=2)

# --- READ DEVICE ID ---
device_id_val = "UNKNOWN_DEVICE"
if DEVICE_CONFIG_FILE.exists():
    try:
        with open(DEVICE_CONFIG_FILE, 'r') as f:
            device_id_val = json.load(f).get("device_id", "UNKNOWN_DEVICE")
    except Exception as e:
        print(f"[Warning] Could not read Device ID: {e}")

# --- READ LINE ID ---  <--- ADD THIS BLOCK
line_id_val = "UNKNOWN_LINE"
line_name_val = "Unknown"
if LINE_CONFIG_FILE.exists():
    try:
        with open(LINE_CONFIG_FILE, 'r') as f:
            data = json.load(f)
            line_id_val = data.get("line_id", "UNKNOWN_LINE")
            line_name_val = data.get("line_name", "Unknown")
    except Exception as e:
        print(f"[Warning] Could not read Line Config: {e}")

# --- GLOBAL VARIABLES ---
processor = None
meas_engine = None
calibrator = None
qc_validator = None
trouser_proc = None
shirt_proc = None
cam_manager = None
sync_manager = None
wifi_manager_instance = None

app_state = {
    "mode": "RAW",
    "settings": {"pixels_per_cm": 0.0, "garment_type": "trousers"},
    "last_raw_frame": None,
    "last_rotation": 0,
    "device_id": device_id_val,
    "line_id": line_id_val,
    "line_name": line_name_val,
    "last_processed_report": None
}

# --- HELPER FUNCTIONS ---

def load_standards():
    try:
        with open(SIZE_STANDARDS_FILE, 'r') as f: return json.load(f)
    except: return garment_config.SIZE_STANDARDS

def get_calibration_value():
    try:
        if CALIBRATION_FILE.exists():
            with open(CALIBRATION_FILE, 'r') as f:
                cal = json.load(f)
                # Older calibrator writes "pixels_per_cm"; the v8.2 calibrator writes "output_ppcm".
                return cal.get("pixels_per_cm") or cal.get("output_ppcm") or 0.0
    except: pass
    return 0.0

def start_server():
    """Starts Uvicorn in a separate thread"""
    uvicorn.run(endpoints_server.app, host="0.0.0.0", port=8000, log_config=None)

# --- UPDATE UI HOOK ---
def prompt_user_for_update(version):
    """Hooks into the web launcher to show the HTML update modal and waits for a click."""
    print(f"[Startup] Prompting user for Update v{version}...")
    
    # 1. Ensure the window is loaded, then trigger the JS function
    time.sleep(1) 
    web_launcher.main_window.evaluate_js(f"showUpdatePrompt('v{version}')")
    
    # 2. Reset the event and PAUSE this thread until the user clicks a button
    web_launcher.global_api.update_event.clear()
    web_launcher.global_api.update_event.wait() 
    
    # 3. Return the boolean result (True for Update, False for Skip)
    return web_launcher.global_api.update_choice

def update_progress_ui(percent):
    """Pushes the download percentage to the HTML Progress bar."""
    if hasattr(web_launcher, 'main_window') and web_launcher.main_window:
        try:
            web_launcher.main_window.evaluate_js(f"updateDownloadProgress({percent})")
        except:
            pass

# --- BACKGROUND STARTUP TASK ---
# This runs concurrently with the Splash Screen
def background_startup():
    global processor, meas_engine, calibrator, qc_validator, trouser_proc, shirt_proc, cam_manager, sync_manager, wifi_manager_instance

    # -----------------------------------------------------------
    # PHASE 0: LICENSE CHECK (BLOCKING)
    # -----------------------------------------------------------
    print(f"[Startup] Phase 0: Verifying License for {__author__}...")
    try:
        from security.license_guard import license_guard
        from security.activator import prompt_for_activation
        
        while True:
            # 1. Validate License
            APP_CONFIG = license_guard.validate()
            
            if APP_CONFIG:
                # 2. VALID! Inject Secure Variables
                os.environ["FACTORY_ID"] = APP_CONFIG.get("FACTORY_ID", "UNKNOWN")
                os.environ["FACTORY_NAME"] = APP_CONFIG.get("FACTORY_NAME", "Unknown Factory")
                os.environ["SUPABASE_URL"] = APP_CONFIG.get("SUPABASE_URL", "")
                os.environ["SUPABASE_KEY"] = APP_CONFIG.get("SUPABASE_KEY", "")
                os.environ["R2_ACCOUNT_ID"] = APP_CONFIG.get("R2_ACCOUNT_ID", "")
                os.environ["R2_ACCESS_KEY_ID"] = APP_CONFIG.get("R2_ACCESS_KEY_ID", "")
                os.environ["R2_SECRET_ACCESS_KEY"] = APP_CONFIG.get("R2_SECRET_ACCESS_KEY", "")
                os.environ["R2_BUCKET_NAME"] = APP_CONFIG.get("R2_BUCKET_NAME", "")
                os.environ["R2_PUBLIC_DOMAIN"] = APP_CONFIG.get("R2_PUBLIC_DOMAIN", "")
                
                print(f"[License] Verified: {os.environ['FACTORY_NAME']}")
                break # Proceed to Phase 1
            else:
                # 3. INVALID! Show Blocking UI (Stops Startup)
                print("[License] Missing or Expired. Prompting User...")
                success = prompt_for_activation(status_message="License Activation Required")
                
                if success:
                    # User activated. Reload guard to pick up new config.
                    license_guard.__init__()
                    continue # Loop back to 'validate()'
                else:
                    # User closed the window. Exit App.
                    print("[License] Activation Cancelled. Shutting down.")
                    sys.exit(0)
                    
    except ImportError:
        print("[License] Security module missing (Dev Mode?). Skipping.")
    except Exception as e:
        print(f"[License] Critical Error: {e}")
        # In production, consider sys.exit(1) here

    # -----------------------------------------------------------
    # PHASE 1: ASSET DECRYPTION (REMOVED)
    # -----------------------------------------------------------
    # We no longer decode the model to disk. 
    # 'inference.py' handles secure in-memory decryption automatically.
    print("[Startup] Phase 1: Initializing Secure Engine...")
    time.sleep(0.5)

    # -----------------------------------------------------------
    # PHASE 2: UPDATES (BLOCKING / INTERACTIVE)
    # -----------------------------------------------------------
    print("[Startup] Phase 2: Checking for Updates...")
    if updater:
        # This function now runs synchronously. It will BLOCK here 
        # until the user skips the update, or until the download finishes.
        # It defaults to run_in_background=False for the startup sequence.
        updater.check_for_updates(
            ask_user_callback=prompt_user_for_update,
            on_progress=update_progress_ui
        )

    # -----------------------------------------------------------
    # PHASE 3: UTILITIES
    # -----------------------------------------------------------
    print("[Startup] Initializing Cloud Sync Manager...")
    try:
        sync_manager = CloudSyncManager(pending_dir=DATA_DIR / "pending_uploads", retry_interval=60)
    except Exception as e:
        print(f"[Startup Error] Sync Manager: {e}")

    print("[Startup] Initializing Wi-Fi Manager...")
    try:
        wifi_manager_instance = wifi_manager.WifiManager()
    except Exception as e:
        print(f"[Startup Error] Wifi Init Failed: {e}")

    # -----------------------------------------------------------
    # PHASE 4: AI ENGINES
    # -----------------------------------------------------------
    print("[Startup] Phase 3: Initializing AI Core...")
    try:
        processor = ImageProcessor()
        meas_engine = MeasurementEngine()
        calibrator = Calibrator()
        qc_validator = QCValidator(tolerance_cm=1.0)
        trouser_proc = TrouserProcessor()
        shirt_proc = ShirtProcessor()
    except Exception as e:
        print(f"[Startup Error] Engine Init Failed: {e}")

    # -----------------------------------------------------------
    # PHASE 5: CAMERA
    # -----------------------------------------------------------
    print("[Startup] Phase 4: Starting Camera System...")
    try:
        cam_manager = CameraManager(width=2880, height=2160)
        
        # --- LOAD SAVED CAMERA SETTINGS FROM JSON ---
        if CALIBRATION_FILE.exists():
            try:
                with open(CALIBRATION_FILE, 'r') as f:
                    calib_data = json.load(f)
                    saved_cam_settings = calib_data.get("camera_settings")
                    if saved_cam_settings:
                        cam_manager.camera_settings.update(saved_cam_settings)
                        cam_manager.settings_pending = True
                        print("[Startup] Applied saved camera hardware settings.")
            except Exception as e:
                print(f"[Startup Error] Failed to load camera settings: {e}")
        # --------------------------------------------
        
        cam_manager.set_processor_callback(process_camera_frame)
        cam_manager.start()
    except Exception as e:
        print(f"[Startup Error] Camera Failed: {e}")
        
    # -----------------------------------------------------------
    # PHASE 6: API SERVER
    # -----------------------------------------------------------
    print("[Startup] Phase 5: Starting UI Server...")
    threading.Thread(target=start_server, daemon=True).start()

# --- CAMERA PROCESSOR CALLBACK ---
def process_camera_frame(frame):
    """
    Applies Business Logic (AI, Visual Guides) to the frame.
    """
    if not cam_manager: return frame

    output = frame.copy()
    
    try:
        rotation = cam_manager.get_rotation()
        is_portrait = rotation in [90, 270]
        current_garment = app_state["settings"]["garment_type"]

        # 1. Draw Guides
        if app_state["mode"] != "CALIBRATION":
            if trouser_proc and current_garment == "trousers":
                output = trouser_proc.draw_alignment_guide(output, is_portrait)
            elif shirt_proc and current_garment.lower() in ["shirt", "t-shirt", "top", "short_sleeve_top"]:
                output = shirt_proc.draw_alignment_guide(output, is_portrait)

        # 2. Run AI Inference
        if app_state["mode"] == "AI" and processor:
            try:
                kps, scores = processor.run_ai_inference(frame)
                standards = load_standards()
                ppcm = app_state["settings"]["pixels_per_cm"]
                if ppcm <= 0: ppcm = get_calibration_value() or 9.0

                fixed_point = None
                if current_garment == "trousers":
                    fixed_point = trouser_proc.get_fixed_reference(is_portrait)
                elif current_garment.lower() in ["shirt", "t-shirt", "top", "short_sleeve_top"]:
                    fixed_point = shirt_proc.get_fixed_reference(is_portrait)

                _, _, _, meas_img, _, _, _, _, _, _ = meas_engine.process(
                    frame, kps, scores, ppcm, 
                    current_garment, 
                    standards,
                    fixed_crotch_point=fixed_point
                )

                output = meas_img
            except Exception as e:
                # Keep camera running even if AI hiccups
                pass
    except Exception as e:
        print(f"[Processor Error] {e}")

    return output

# --- MAIN ENTRY POINT ---
if __name__ == "__main__":
    print(f"Initializing GarmentQC AI System ({__copyright__})...")
    
    # Launch Splash Screen IMMEDIATELY.
    # 'background_startup' runs in a thread. 
    # If License is invalid, 'background_startup' will pop the Activation Window 
    # ON TOP of the Splash Screen, blocking progress until resolved.
    web_launcher.launch_kiosk(HOST_WEB_URL, startup_callback=background_startup)