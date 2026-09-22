import cv2
import numpy as np
import json
import os
import sys
import copy
import platform
import base64
import webbrowser
import threading
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional

# --- NEW CAMERA MANAGER ---
from camera_manager import CameraManager

# --- FASTAPI & SERVER ---
import uvicorn
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
# NEW: Imports for serving the UI locally
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# --- YOUR EXISTING MODULES ---
from inference import ImageProcessor
from processing_engine import MeasurementEngine
from calibrator import Calibrator
from qc_validator import QCValidator
import garment_config

# ==========================================
# 1. SETUP & PATHS (Updated for Local/Frozen support)
# ==========================================
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if getattr(sys, 'frozen', False):
    # Running as compiled exe
    BASE_DIR = Path(sys._MEIPASS)
    PROJECT_ROOT = Path(os.path.dirname(sys.executable))
else:
    # Running as script
    BASE_DIR = Path(__file__).parent
    PROJECT_ROOT = BASE_DIR

DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
REFERENCE_DIR = DATA_DIR / "references"
SIZE_STANDARDS_FILE = DATA_DIR / "size_standards.json"
CALIBRATION_FILE = DATA_DIR / "calibration.json"

# Create directories if missing
for d in [REPORTS_DIR, REFERENCE_DIR]:
    os.makedirs(d, exist_ok=True)

if not SIZE_STANDARDS_FILE.exists():
    with open(SIZE_STANDARDS_FILE, 'w') as f:
        json.dump(garment_config.SIZE_STANDARDS, f, indent=2)

# ==========================================
# 2. CONFIGURATION & LOGGING
# ==========================================
# This URL is for syncing data to your central database/cloud
HOST_WEB_URL = "http://192.168.8.149:3000" 

API_UPLOAD_REPORT = f"{HOST_WEB_URL}/api/upload-report"
API_UPLOAD_CALIB = f"{HOST_WEB_URL}/api/upload-calibration"

if getattr(sys, 'frozen', False):
    log_path = Path(sys.executable).parent / "app_logs.txt"
    sys.stdout = open(log_path, "w", buffering=1)
    sys.stderr = open(log_path, "w", buffering=1)

# ==========================================
# 3. INITIALIZATION
# ==========================================
CROTCH_POINT_LANDSCAPE = (640, 250) 
CROTCH_POINT_PORTRAIT = (360, 450)

# Use resource_path for models to work in frozen mode
# Note: 'model_path' argument removed as ImageProcessor handles it internally
processor = ImageProcessor() 
meas_engine = MeasurementEngine()
calibrator = Calibrator()
qc_validator = QCValidator(tolerance_cm=1.0)
cam_manager = CameraManager(width=1280, height=720)

app = FastAPI()

# Enable CORS so you can access this from other IPs
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, 
                   allow_methods=["*"], allow_headers=["*"])

# NEW: Mount Static Files (Frontend UI)
# If a 'static' folder exists, serve it (The React Build)
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# NEW: Mount Data Directory (To view saved images/reports via URL)
if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

# ==========================================
# APP STATE
# ==========================================
app_state = {
    "mode": "RAW",  
    "settings": {
        "pixels_per_cm": 0.0,
        "garment_type": "trousers"
    },
    "last_raw_frame": None,     
    "last_rotation": 0          
}

# ==========================================
# HELPERS
# ==========================================
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

def encode_image(image):
    _, buffer = cv2.imencode('.jpg', image)
    return base64.b64encode(buffer).decode('utf-8')

def sync_to_cloud(url, files=None, data=None):
    def _send():
        try:
            # Only sync if the central host is reachable
            requests.post(url, files=files, data=data, timeout=5)
        except: pass
    threading.Thread(target=_send, daemon=True).start()

# ==========================================
# CAMERA CALLBACK
# ==========================================
def process_camera_frame(frame):
    output = frame.copy()
    h, w = output.shape[:2]
    
    rotation = cam_manager.get_rotation()
    is_portrait = rotation in [90, 270]
    
    # BACKEND LOGIC: Only draw UI if NOT in calibration mode
    if app_state["mode"] != "CALIBRATION":
        fixed_point = CROTCH_POINT_PORTRAIT if is_portrait else CROTCH_POINT_LANDSCAPE
        
        if app_state["settings"]["garment_type"] == "trousers":
            cx, cy = fixed_point
            if cx < w and cy < h:
                cv2.circle(output, (cx, cy), 6, (0, 0, 255), -1)
                cv2.circle(output, (cx, cy), 25, (0, 255, 255), 2)
                cv2.line(output, (cx - 40, cy), (cx + 40, cy), (0, 255, 255), 1)
                cv2.line(output, (cx, cy - 40), (cx, cy + 40), (0, 255, 255), 1)
                cv2.putText(output, "ALIGN CROTCH", (cx - 70, cy - 40),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    if app_state["mode"] == "AI":
        try:
            kps, scores = processor.run_ai_inference(frame)
            standards = load_standards()
            ppcm = app_state["settings"]["pixels_per_cm"]
            if ppcm <= 0: ppcm = get_calibration_value() or 9.0
            
            fixed_point = CROTCH_POINT_PORTRAIT if is_portrait else CROTCH_POINT_LANDSCAPE
            pt_arg = fixed_point if app_state["settings"]["garment_type"] == "trousers" else None
            
            # --- FIX: Unpack 10 values correctly ---
            # 0:proc_img, 1:img_detect, 2:edge_map, 3:img_measure, 4:overlay_detect, 5:overlay_measure, 6:data, 7:size, 8:conf, 9:suggs
            _, _, _, meas_img, _, _, _, _, _, _ = meas_engine.process(
                frame, kps, scores, ppcm, 
                app_state["settings"]["garment_type"], 
                standards,
                fixed_crotch_point=pt_arg
            )
            output = meas_img
        except Exception:
            # Keep running if AI fails momentarily
            pass
            
    return output

cam_manager.set_processor_callback(process_camera_frame)
cam_manager.start()

# ==========================================
# API ENDPOINTS
# ==========================================

# UPDATED: Serve index.html instead of just JSON status
@app.get("/")
def read_index():
    index_path = BASE_DIR / "static" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"status": "ELIoT Firmware Running (UI not found in /static)"}

@app.get("/api/cameras")
def get_cameras(): return cam_manager.list_cameras()

@app.post("/api/set-camera")
def set_camera(camera_id: int = Form(...)):
    cam_manager.set_camera(camera_id)
    return {"status": "ok"}

@app.post("/api/rotate-camera")
def rotate_camera():
    current = cam_manager.get_rotation()
    new_angle = (current + 90) % 360
    cam_manager.set_rotation(new_angle)
    return {"status": "ok", "rotation": new_angle}

@app.post("/api/set-mode")
def set_mode(mode: str = Form(...), 
             pixels_per_cm: float = Form(0.0), 
             garment_type: str = Form("trousers")):
    app_state["mode"] = mode
    if pixels_per_cm > 0:
        app_state["settings"]["pixels_per_cm"] = pixels_per_cm
    app_state["settings"]["garment_type"] = garment_type
    return {"status": "ok"}

@app.get("/api/config")
def get_config():
    config = {}
    for g_type, data in garment_config.GARMENT_CONFIG.items():
        config[g_type] = {
            "display_name": data.get("display_name", g_type),
            "measurements": [m[2] for m in data.get("measurements", [])]
        }
    return config

@app.get("/api/calibration")
def get_calibration():
    return {"pixels_per_cm": get_calibration_value()}

@app.post("/process")
async def process(file: UploadFile = File(None), 
                  pixels_per_cm: float = Form(0.0), 
                  manual_garment_type: str = Form("trousers"), 
                  save_report: bool = Form(False),
                  use_internal_cam: bool = Form(False)):
    
    img = None
    active_rotation = 0
    
    if save_report and app_state["last_raw_frame"] is not None:
        img = app_state["last_raw_frame"].copy()
        active_rotation = app_state["last_rotation"] 
    else:
        if use_internal_cam:
            img = cam_manager.get_latest_frame()
            active_rotation = cam_manager.get_rotation()
        elif file:
            img = cv2.imdecode(np.frombuffer(await file.read(), np.uint8), cv2.IMREAD_COLOR)

    if img is None: return {"error": "Camera not ready or image missing"}
    if not save_report:
        app_state["last_raw_frame"] = img.copy()
        app_state["last_rotation"] = active_rotation 

    final_ppcm = pixels_per_cm if pixels_per_cm > 0 else (get_calibration_value() or 9.0)
    kps, scores = processor.run_ai_inference(img)
    standards = load_standards()
    
    fixed_pt = None
    if manual_garment_type == "trousers":
        fixed_pt = CROTCH_POINT_PORTRAIT if active_rotation in [90, 270] else CROTCH_POINT_LANDSCAPE

    # --- FIX: Unpack 10 values correctly (Ignore overlays and proc_img) ---
    # 0:proc_img, 1:img_detect, 2:edge_map, 3:img_measure, 4:overlay_detect, 5:overlay_measure, 6:data, 7:size, 8:conf, 9:suggs
    _, det, edge, meas, _, _, data, size, conf, suggs = meas_engine.process(
        img, kps, scores, final_ppcm, manual_garment_type, standards,
        fixed_crotch_point=fixed_pt
    )
    
    qc_status = "UNKNOWN"
    qc_failures = []
    if size and size != "Unknown":
        qc_status, detailed_results, _ = qc_validator.validate_against_size_standard(data, size, standards, manual_garment_type)
        qc_failures = [f"{r['name']}: {r['measured']}cm (Exp: {r['reference']}cm)" for r in detailed_results if r['status'] == 'FAIL']

    rid = None
    if save_report:
        rid = f"{manual_garment_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        rpt = {
            "id": rid, 
            "timestamp": str(datetime.now()), 
            "garment_type": manual_garment_type, 
            "detected_size": size, 
            "confidence": conf, 
            "measurements": data, 
            "pixels_per_cm": final_ppcm, 
            "qc_status": qc_status
        }
        
        with open(REPORTS_DIR / f"{rid}.json", 'w') as f: 
            json.dump(rpt, f, indent=2)
        cv2.imwrite(str(REPORTS_DIR / f"{rid}_measure.jpg"), meas)
        
        # Sync to Web Host (DB)
        if HOST_WEB_URL:
            _, img_encoded = cv2.imencode('.jpg', meas)
            sync_to_cloud(
                API_UPLOAD_REPORT, 
                files={'image': (f"{rid}.jpg", img_encoded.tobytes(), 'image/jpeg')}, 
                data={'report_json': json.dumps(rpt)}
            )

    return {
        "report_id": rid, 
        "detect_image": "data:image/jpeg;base64," + encode_image(det),
        "measure_image": "data:image/jpeg;base64," + encode_image(meas),
        "data": data, 
        "detected_size": size, 
        "qc_status": qc_status, 
        "qc_failures": qc_failures
    }

@app.post("/api/calibrate")
async def calibrate(t1: int = Form(50), t2: int = Form(150)):
    # 1. Grab raw unrotated frame from CameraManager
    with cam_manager.lock:
        img = getattr(cam_manager, 'raw_frame', None)
    
    if img is None:
        return {"success": False, "message": "Camera hardware not ready"}

    # 2. Normalize to Landscape (Forces 8.9 PPCM consistently)
    h, w = img.shape[:2]
    if h > w:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    
    # 3. Detect A4 paper
    ppcm, dbg, _ = calibrator.get_pixels_per_cm(img, t1, t2)
    
    if ppcm:
        with open(CALIBRATION_FILE, 'w') as f:
            json.dump({"pixels_per_cm": ppcm, "timestamp": str(datetime.now())}, f)
        
        if HOST_WEB_URL:
             _, img_encoded = cv2.imencode('.jpg', img)
             sync_to_cloud(
                API_UPLOAD_CALIB, 
                files={'image': ('cal_raw.jpg', img_encoded.tobytes(), 'image/jpeg')}, 
                data={'pixels_per_cm': ppcm}
            )
            
    return {
        "success": True if ppcm else False, 
        "pixels_per_cm": ppcm, 
        "debug_image": "data:image/jpeg;base64," + encode_image(dbg),
        "message": f"Detected: {ppcm:.2f} px/cm" if ppcm else "A4 not found"
    }

@app.get("/api/reports")
def get_reps(garment_type: Optional[str] = None):
    reps = []
    if REPORTS_DIR.exists():
        for f in sorted(os.listdir(REPORTS_DIR), reverse=True):
            if f.endswith('.json'):
                with open(REPORTS_DIR / f) as j:
                    d = json.load(j)
                    if not garment_type or d.get('garment_type') == garment_type: reps.append(d)
    return reps

@app.get("/api/report/{rid}")
def get_rep_det(rid: str):
    p = REPORTS_DIR / f"{rid}.json"
    if not p.exists(): raise HTTPException(404, detail="Report not found")
    with open(p) as f: d = json.load(f)
    img_path = REPORTS_DIR / f"{rid}_measure.jpg"
    if img_path.exists():
        d['measure_image'] = "data:image/jpeg;base64," + encode_image(cv2.imread(str(img_path)))
    return d

if __name__ == "__main__":
    def open_browser():
        time.sleep(2)
        # UPDATED: Open Localhost so you can see the UI immediately on this machine
        webbrowser.open("http://localhost:8000")
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Listen on 0.0.0.0 so you can also access via IP from other devices
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)