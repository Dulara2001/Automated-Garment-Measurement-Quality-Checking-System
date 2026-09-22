import cv2
import numpy as np
import json
import os
import sys
import math
import threading
import requests
import base64
from datetime import datetime
from typing import Optional

# --- FASTAPI ---
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import asyncio
from fastapi import Request


# --- MODULES ---
from camera_manager import CameraManager
import garment_config


# --- CONNECT TO MAIN APPLICATION ---
# This block ensures we access the ACTIVE variables (cam_manager, processor, etc.)
# from the running windows_test.py, rather than importing a new empty instance.
try:
    import windows_test
    # Check if windows_test has initialized globals. If not, it means windows_test
    # is running as __main__, so we should grab __main__ instead.
    if not hasattr(windows_test, 'cam_manager') or windows_test.cam_manager is None:
        import __main__ as windows_test
except ImportError:
    # If windows_test cannot be imported (e.g. circular dependency), assume it is __main__
    import __main__ as windows_test

# ==========================================
# FASTAPI APP DEFINITION
# ==========================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# Mount static files using paths defined in windows_test
if hasattr(windows_test, 'PROJECT_ROOT') and (windows_test.PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=str(windows_test.PROJECT_ROOT / "static")), name="static")

if hasattr(windows_test, 'DATA_DIR') and windows_test.DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(windows_test.DATA_DIR)), name="data")


# ==========================================
# DATA MODELS
# ==========================================
class CalibrationSaveRequest(BaseModel):
    pixels_per_cm: float

class WifiConnectRequest(BaseModel):
    ssid: str
    password: str

class ToggleRequest(BaseModel):
    state: bool  # True = enable, False = disable

class ForgetNetworkRequest(BaseModel):
    ssid: str

class DeviceIDRequest(BaseModel):
    device_id: str

class LineSelectRequest(BaseModel):
    line_id: str
    line_name: Optional[str] = "Unknown"

# camera settings request model
class CameraSettingsRequest(BaseModel):
    brightness: int
    contrast: int

class FocusRequest(BaseModel):
    focus: int
    autofocus: bool

# ==========================================
# HELPER: BACKGROUND CLOUD TASK
# ==========================================
def offload_cloud_task(rid, clean_img, ov_det, ov_meas, manual_garment_type, size, conf, data, final_ppcm, qc_status, qc_failures, style=""):
    """
    Runs in the background AFTER the UI has received its response.
    Handles slow image compression (WebP) and Database Sync to prevent UI freezing.
    """
    try:
        # Base Image (Clean Background) -> WebP (Compressed for Cloud)
        _, buf_base = cv2.imencode('.webp', clean_img, [cv2.IMWRITE_WEBP_QUALITY, 30])
        b64_base = "data:image/webp;base64," + base64.b64encode(buf_base).decode('utf-8')
        
        # Detect Overlay -> WebP
        _, buf_det = cv2.imencode('.webp', ov_det, [cv2.IMWRITE_WEBP_QUALITY, 60])
        b64_det = "data:image/webp;base64," + base64.b64encode(buf_det).decode('utf-8')

        # Measure Overlay -> WebP
        _, buf_meas = cv2.imencode('.webp', ov_meas, [cv2.IMWRITE_WEBP_QUALITY, 60])
        b64_meas = "data:image/webp;base64," + base64.b64encode(buf_meas).decode('utf-8')

        # FETCH DEVICE AND LINE ID FROM APP STATE
        device_id = "UNKNOWN"
        line_id = "UNKNOWN_LINE"
        line_name = "Unknown"
        
        if hasattr(windows_test, 'app_state'):
            device_id = windows_test.app_state.get("device_id", "UNKNOWN")
            line_id = windows_test.app_state.get("line_id", "UNKNOWN_LINE")
            # line_name = windows_test.app_state.get("line_name", "Unknown")

        rpt = {
            "id": rid, 
            "device_id": device_id,  
            "line_id": line_id,          
            "line_name": line_name,      
            "timestamp": str(datetime.now()), 
            "garment_type": manual_garment_type, 
            "style": style,          
            "detected_size": size, 
            "confidence": conf,
            "measurements": data, 
            "pixels_per_cm": final_ppcm, 
            "qc_status": qc_status, 
            "qc_failures": qc_failures,
            # IMAGES SENT TO CLOUD DATABASE
            "base_image": b64_base,
            "detect_overlay": b64_det,
            "measure_overlay": b64_meas
        }
            
        # DIRECT SYNC CALL
        if hasattr(windows_test, 'sync_manager') and windows_test.sync_manager:
            windows_test.sync_manager.upload_now(rpt)
        else:
            print("[Background] Warning: SyncManager not active.")
            
    except Exception as e:
        print(f"[Background Error] Failed to process cloud upload: {e}")

# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/")
def read_index():
    index_path = windows_test.BASE_DIR / "static" / "index.html"
    if index_path.exists(): 
        return FileResponse(str(index_path))
    return {"status": "ELIoT Firmware Running"}

@app.get("/video_feed")
def video_feed():
    """
    LOCAL VIDEO STREAM
    This stream is served locally to localhost. It is NOT uploaded to the cloud.
    """
    if not windows_test.cam_manager: 
        return {"error": "Camera Initializing..."}
    
    # Use the generator from the active CameraManager instance in windows_test
    return StreamingResponse(
        windows_test.cam_manager.stream_generator(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/cameras")
def get_cameras(): 
    return windows_test.cam_manager.list_cameras() if windows_test.cam_manager else []

@app.post("/api/set-camera")
def set_camera(camera_id: int = Form(...)):
    if windows_test.cam_manager: 
        windows_test.cam_manager.set_camera(camera_id)
    return {"status": "ok"}

# This endpoint receives brightness and contrast settings from the UI and applies them to the camera hardware.
@app.get("/api/camera/settings")
def get_camera_settings():
    """Fetches current hardware settings so the UI sliders match reality when opened."""
    if windows_test.cam_manager:
        return {
            "success": True, 
            "settings": windows_test.cam_manager.camera_settings
        }
    return {"success": False, "message": "Camera not ready"}

@app.post("/api/camera/settings/preview")
def preview_camera_settings(settings: CameraSettingsRequest):
    """Real-time preview of brightness and contrast without saving."""
    if windows_test.cam_manager:
        windows_test.cam_manager.set_camera_controls(settings.dict())
        return {"success": True}
    return {"success": False, "message": "Camera manager not ready"}

@app.post("/api/camera/settings/save")
def save_camera_settings(settings: CameraSettingsRequest):
    """Handles the 'Apply Changes' button, and SAVES all settings to calibration.json"""
    if windows_test.cam_manager:
        # 1. Update live hardware in memory
        windows_test.cam_manager.set_camera_controls(settings.dict())
        
        # 2. Save the complete state to JSON
        calib_file = windows_test.CALIBRATION_FILE
        data = {}
        if calib_file.exists():
            try:
                with open(calib_file, 'r') as f:
                    data = json.load(f)
            except Exception: 
                pass
                
        # Grab the fully updated dictionary which contains focus and autofocus states too
        data["camera_settings"] = windows_test.cam_manager.camera_settings
        
        with open(calib_file, 'w') as f:
            json.dump(data, f, indent=2)
            
        return {"success": True, "message": "Hardware settings applied and saved permanently."}
    return {"success": False, "message": "Camera manager not ready"}

@app.post("/api/camera/focus")
def update_camera_focus(req: FocusRequest):
    """Handles real-time Focus slider and Auto-focus toggle (Saved later on Apply)"""
    if windows_test.cam_manager:
        windows_test.cam_manager.set_focus(req.focus, req.autofocus)
        return {"success": True}
    return {"success": False}

@app.post("/api/rotate-camera")
def rotate_camera():
    if windows_test.cam_manager:
        current = windows_test.cam_manager.get_rotation()
        new_angle = (current + 90) % 360
        windows_test.cam_manager.set_rotation(new_angle)
        return {"status": "ok", "rotation": new_angle}
    return {"status": "error"}

@app.post("/api/set-mode")
def set_mode(mode: str = Form(...), 
             pixels_per_cm: float = Form(0.0), 
             garment_type: str = Form("trousers"),
             standards: Optional[str] = Form(None)): 
    
    # --- DEBUG: PRINT UI PACKET (INCOMING) ---
    print(f"\n[UI Request] Set Mode: mode={mode}, ppcm={pixels_per_cm}, type={garment_type}")
    
    # Update the app_state dictionary located in windows_test
    windows_test.app_state["mode"] = mode
    if pixels_per_cm > 0:
        windows_test.app_state["settings"]["pixels_per_cm"] = pixels_per_cm
    windows_test.app_state["settings"]["garment_type"] = garment_type
    
    # Update Standards File locally if provided
    if standards and hasattr(windows_test, 'sync_manager') and windows_test.sync_manager:
        windows_test.sync_manager.save_local_standards(standards, windows_test.SIZE_STANDARDS_FILE)

    return {"status": "ok"}

@app.get("/api/config")
def get_config():
    """
    Translates the universal letter codes back into human-readable names 
    for the Frontend UI, and hides any measurements that are not currently active.
    """
    if hasattr(windows_test, 'load_standards'):
        standards = windows_test.load_standards()
    else:
        standards = garment_config.SIZE_STANDARDS
        
    # Get active key measurements from the JSON to filter UI output
    key_measurements_map = standards.get("key_measurements", garment_config.KEY_MEASUREMENTS)
    
    config = {}
    for g_type, data in garment_config.GARMENT_CONFIG.items():
        # Clean up active keys for this specific garment type (removing nulls)
        active_keys_raw = key_measurements_map.get(g_type, [])
        active_keys = [k for k in active_keys_raw if k is not None]

        # Build a translation dictionary
        code_mapper = {}
        if g_type in standards:
            sz_data = standards[g_type]
            sizes_dict = sz_data.get('sizes', sz_data) if isinstance(sz_data, dict) else {}
            if sizes_dict:
                first_size = list(sizes_dict.values())[0]
                if isinstance(first_size, list):
                    for item in first_size:
                        c = item.get('description', '').strip() 
                        n = item.get('name', c)                 
                        if c: code_mapper[c] = n
        
        # Translate the measurements AND apply the filter
        display_measurements = []
        for m in data.get("measurements", []):
            code = m[2].strip()
            
            # ---> SKIP SENDING TO UI IF NOT IN KEY MEASUREMENTS <---
            if active_keys and code not in active_keys:
                continue
                
            translated_name = code_mapper.get(code, code)
            display_measurements.append(translated_name)
            
        config[g_type] = {
            "display_name": data.get("display_name", g_type),
            "measurements": display_measurements
        }
    return config

@app.get("/api/calibration")
def get_calibration():
    # Call helper function from windows_test
    return {"pixels_per_cm": windows_test.get_calibration_value()}

async def capture_burst_raw(cam_manager, ai_processor, num_frames=1):
    """
    Captures a burst of frames and runs AI inference on each independently.
    Returns lists of frames, keypoints, and scores for the measurement engine.
    Set to 3 frames for faster processing.
    """
    images = []
    all_kps = []
    all_scores = []
    
    for _ in range(num_frames):
        img = cam_manager.get_latest_frame()
        if img is not None:
            kps, scores = ai_processor.run_ai_inference(img)
            images.append(img)
            all_kps.append(kps)
            all_scores.append(scores)
        await asyncio.sleep(0.01) # 10ms delay to catch micro-variations
        
    if not images:
        return None, None, None
        
    return images, all_kps, all_scores

@app.post("/process")
async def process(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(None), 
    pixels_per_cm: float = Form(0.0), 
    manual_garment_type: str = Form("trousers"), 
    save_report: bool = Form(False), # Ignored while manual buttons are active
    use_internal_cam: bool = Form(False)
):
    
    img_input = None
    kps_input = []
    scores_input = []
    active_rotation = 0
    
    # ========================================================
    # BURST CAPTURE LOGIC
    # ========================================================
    if save_report and windows_test.app_state["last_raw_frame"] is not None:
        img_input = windows_test.app_state["last_raw_frame"].copy()
        active_rotation = windows_test.app_state["last_rotation"] 
        kps_input, scores_input = windows_test.processor.run_ai_inference(img_input)
    else:
        if use_internal_cam and windows_test.cam_manager:
            active_rotation = windows_test.cam_manager.get_rotation()
            # GET LISTS OF IMAGES AND AI POINTS (3 FRAMES FOR MAXIMUM STABILITY)
            img_input, kps_input, scores_input = await capture_burst_raw(
                windows_test.cam_manager, windows_test.processor, num_frames=3
            )
        elif file:
            img_input = cv2.imdecode(np.frombuffer(await file.read(), np.uint8), cv2.IMREAD_COLOR)
            active_rotation = 0
            kps_input, scores_input = windows_test.processor.run_ai_inference(img_input)

    if img_input is None: return {"error": "Camera not ready or capture failed"}
    
    if not save_report:
        # Save the middle frame for caching if it's a burst list
        if isinstance(img_input, list):
            windows_test.app_state["last_raw_frame"] = img_input[len(img_input)//2].copy()
        else:
            windows_test.app_state["last_raw_frame"] = img_input.copy()
        windows_test.app_state["last_rotation"] = active_rotation 

    final_ppcm = pixels_per_cm if pixels_per_cm > 0 else (windows_test.get_calibration_value() or 9.0)
    standards = windows_test.load_standards()
    
    fixed_point = None
    is_port = active_rotation in [90, 270]
    
    if manual_garment_type == "trousers" and windows_test.trouser_proc:
        fixed_point = windows_test.trouser_proc.get_fixed_reference(is_port)
    elif manual_garment_type.lower() in ["shirt", "t-shirt", "top", "short_sleeve_top"] and windows_test.shirt_proc:
        fixed_point = windows_test.shirt_proc.get_fixed_reference(is_port)

    # HAND FULL LIST TO PROCESSING ENGINE
    clean_img, det, edge, meas, ov_det, ov_meas, data, size, conf, suggs = windows_test.meas_engine.process(
        img_input, kps_input, scores_input, final_ppcm, manual_garment_type, standards,
        fixed_crotch_point=fixed_point
    )
    
    qc_status = "PASS"
    qc_failures = []
    
    for m in data:
        if m.get('status') == 'FAIL':
            unit_label = m.get('unit', 'in')
            qc_failures.append(f"{m['name']}: {m['value']}{unit_label} (Out of Tolerance)")
            qc_status = "FAIL"
    
    if size in ["Unknown", "FAIL"]:
        qc_status = "FAIL"

    # [SAFETY CHECKS] A capture the engine cannot trust (garment cut off, upside down, not
    # trousers, measurements missing) must never PASS. The messages go into qc_failures so the
    # existing QC FAIL popup shows the operator what to fix.
    capture_warnings = getattr(windows_test.meas_engine, "last_warnings", []) or []
    for w in capture_warnings:
        if w.get("level") == "retake":
            qc_status = "FAIL"
            qc_failures.append(f"RETAKE: {w['message']}")

    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    rid = f"{manual_garment_type}_{timestamp_str}"
    
    # =========================================================
    # CACHE FOR MANUAL SAVE ENDPOINT (ACTIVE)
    # =========================================================
    windows_test.app_state["last_processed_report"] = {
        "id": rid,
        "clean_img": clean_img.copy(),
        "ov_det": ov_det.copy(),
        "ov_meas": ov_meas.copy(),
        "manual_garment_type": manual_garment_type,
        "size": size,
        "conf": conf,
        "data": data,
        "final_ppcm": final_ppcm,
        "qc_failures": qc_failures,
        "auto_qc_status": qc_status
    }
# ********************************* Don't remove this part here *************************************
    # =========================================================
    # FUTURE AUTO-SAVE FEATURE (COMMENTED OUT)
    # =========================================================
    # Uncomment this block, and remove the caching block above, 
    # to revert back to saving on capture automatically.
    # ---------------------------------------------------------
    # background_tasks.add_task(
    #     offload_cloud_task,
    #     rid, 
    #     clean_img.copy(), 
    #     ov_det.copy(), 
    #     ov_meas.copy(), 
    #     manual_garment_type, 
    #     size, 
    #     conf, 
    #     data, 
    #     final_ppcm, 
    #     qc_status, 
    #     qc_failures,
    #     "" # Style is empty on auto-capture unless passed
    # )
    # =========================================================

    del clean_img, ov_det, ov_meas

    # PREPARE FAST LOCAL UI RESPONSE
    _, meas_buf = cv2.imencode('.jpg', meas, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
    meas_b64 = "data:image/jpeg;base64," + base64.b64encode(meas_buf).decode('utf-8')
    del meas, meas_buf
    
    _, det_buf = cv2.imencode('.jpg', det, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
    det_b64 = "data:image/jpeg;base64," + base64.b64encode(det_buf).decode('utf-8')
    del det, det_buf

    # 1. FETCH THE DEVICE ID FROM APP STATE
    device_id = "UNKNOWN"
    if hasattr(windows_test, 'app_state'):
        device_id = windows_test.app_state.get("device_id", "UNKNOWN")

    response_data = {
        "report_id": rid, 
        "device_id": device_id,
        "detect_image": det_b64, 
        "measure_image": meas_b64,
        "data": data, 
        "detected_size": size, 
        "confidence": conf, 
        "qc_status": qc_status, 
        "qc_failures": qc_failures,
        "warnings": capture_warnings
    }

    debug_packet = response_data.copy()
    debug_packet["detect_image"] = "<Base64_Hidden>"
    debug_packet["measure_image"] = "<Base64_Hidden>"
    print(f"\n[Server Response] Process Packet: {json.dumps(debug_packet, default=str)}")

    return response_data

# @app.post("/process")
# async def process(
#     background_tasks: BackgroundTasks, 
#     file: UploadFile = File(None), 
#     pixels_per_cm: float = Form(0.0), 
#     manual_garment_type: str = Form("trousers"), 
#     save_report: bool = Form(False), # Ignored while manual buttons are active
#     use_internal_cam: bool = Form(False)
# ):
    
#     img = None
#     active_rotation = 0
    
#     if save_report and windows_test.app_state["last_raw_frame"] is not None:
#         img = windows_test.app_state["last_raw_frame"].copy()
#         active_rotation = windows_test.app_state["last_rotation"] 
#     else:
#         if use_internal_cam and windows_test.cam_manager:
#             img = windows_test.cam_manager.get_latest_frame()
#             active_rotation = windows_test.cam_manager.get_rotation()
#         elif file:
#             img = cv2.imdecode(np.frombuffer(await file.read(), np.uint8), cv2.IMREAD_COLOR)

#     if img is None: return {"error": "Camera not ready"}
    
#     if not save_report:
#         windows_test.app_state["last_raw_frame"] = img.copy()
#         windows_test.app_state["last_rotation"] = active_rotation 

#     final_ppcm = pixels_per_cm if pixels_per_cm > 0 else (windows_test.get_calibration_value() or 9.0)
    
#     kps, scores = windows_test.processor.run_ai_inference(img)
#     standards = windows_test.load_standards()
    
#     fixed_point = None
#     is_port = active_rotation in [90, 270]
    
#     if manual_garment_type == "trousers" and windows_test.trouser_proc:
#         fixed_point = windows_test.trouser_proc.get_fixed_reference(is_port)
#     elif manual_garment_type.lower() in ["shirt", "t-shirt", "top", "short_sleeve_top"] and windows_test.shirt_proc:
#         fixed_point = windows_test.shirt_proc.get_fixed_reference(is_port)

#     clean_img, det, edge, meas, ov_det, ov_meas, data, size, conf, suggs = windows_test.meas_engine.process(
#         img, kps, scores, final_ppcm, manual_garment_type, standards,
#         fixed_crotch_point=fixed_point
#     )
    
#     #     qc_status = "PASS"
#     qc_failures = []
#     
#     for m in data:
#         if m.get('status') == 'FAIL':
#             unit_label = m.get('unit', 'in')
#             qc_failures.append(f"{m['name']}: {m['value']}{unit_label} (Out of Tolerance)")
#             qc_status = "FAIL"
#     
#     if size in ["Unknown", "FAIL"]:
#         qc_status = "FAIL"

#     timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
#     rid = f"{manual_garment_type}_{timestamp_str}"
    
#     # =========================================================
#     # CACHE FOR MANUAL SAVE ENDPOINT (ACTIVE)
#     # =========================================================
#     windows_test.app_state["last_processed_report"] = {
#         "id": rid,
#         "clean_img": clean_img.copy(),
#         "ov_det": ov_det.copy(),
#         "ov_meas": ov_meas.copy(),
#         "manual_garment_type": manual_garment_type,
#         "size": size,
#         "conf": conf,
#         "data": data,
#         "final_ppcm": final_ppcm,
#         "qc_failures": qc_failures,
#         "auto_qc_status": qc_status
#     }
# # ********************************* Don't remove this part here *************************************
#     # =========================================================
#     # FUTURE AUTO-SAVE FEATURE (COMMENTED OUT)
#     # =========================================================
#     # Uncomment this block, and remove the caching block above, 
#     # to revert back to saving on capture automatically.
#     # ---------------------------------------------------------
#     # background_tasks.add_task(
#     #     offload_cloud_task,
#     #     rid, 
#     #     clean_img.copy(), 
#     #     ov_det.copy(), 
#     #     ov_meas.copy(), 
#     #     manual_garment_type, 
#     #     size, 
#     #     conf, 
#     #     data, 
#     #     final_ppcm, 
#     #     qc_status, 
#     #     qc_failures,
#     #     "" # Style is empty on auto-capture unless passed
#     # )
#     # =========================================================

#     del clean_img, ov_det, ov_meas

#     # PREPARE FAST LOCAL UI RESPONSE
#     _, meas_buf = cv2.imencode('.jpg', meas, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
#     meas_b64 = "data:image/jpeg;base64," + base64.b64encode(meas_buf).decode('utf-8')
#     del meas, meas_buf
    
#     _, det_buf = cv2.imencode('.jpg', det, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
#     det_b64 = "data:image/jpeg;base64," + base64.b64encode(det_buf).decode('utf-8')
#     del det, det_buf

#     # 1. FETCH THE DEVICE ID FROM APP STATE
#     device_id = "UNKNOWN"
#     if hasattr(windows_test, 'app_state'):
#         device_id = windows_test.app_state.get("device_id", "UNKNOWN")

#     response_data = {
#         "report_id": rid, 
#         "device_id": device_id,
#         "detect_image": det_b64, 
#         "measure_image": meas_b64,
#         "data": data, 
#         "detected_size": size, 
#         "confidence": conf, 
#         "qc_status": qc_status, 
#         "qc_failures": qc_failures
#     }

#     debug_packet = response_data.copy()
#     debug_packet["detect_image"] = "<Base64_Hidden>"
#     debug_packet["measure_image"] = "<Base64_Hidden>"
#     print(f"\n[Server Response] Process Packet: {json.dumps(debug_packet, default=str)}")

#     return response_data


# ==========================================
# MANUAL QC SAVE ENDPOINT
# ==========================================
@app.post("/save-qc-report")
def save_qc_report(req: dict, background_tasks: BackgroundTasks):
    """
    Triggers DB save manually from the UI.
    """
    # Extract data from the UI payload
    report_id = req.get("report_id")
    manual_status = req.get("manual_qc_status", "PASS")
    style_code = req.get("style", "")
    override_size = req.get("size", "")
    
    cached = windows_test.app_state.get("last_processed_report")
    
    if not cached or cached["id"] != report_id:
        return {
            "success": False, 
            "message": "Report data expired or ID mismatch. Please capture again."
        }
        
    final_size = override_size if override_size else cached["size"]
        
    # Queue the background upload
    background_tasks.add_task(
        offload_cloud_task,
        cached["id"],
        cached["clean_img"],
        cached["ov_det"],
        cached["ov_meas"],
        cached["manual_garment_type"],
        final_size,
        cached["conf"],
        cached["data"],
        cached["final_ppcm"],
        manual_status,
        cached["qc_failures"],
        style_code
    )
    
    # Clear the cache
    windows_test.app_state["last_processed_report"] = None
    
    return {"success": True, "message": f"QC Report saved as {manual_status}"}


# @app.post("/api/calibrate")
# async def calibrate(t1: int = Form(50), t2: int = Form(150)):
#     if not windows_test.cam_manager: 
#         return {"success": False, "message": "Camera not ready"}

#     with windows_test.cam_manager.lock:
#         img = getattr(windows_test.cam_manager, 'raw_frame', None)
    
#     if img is None: 
#         return {"success": False, "message": "Camera hardware not ready"}

#     h, w = img.shape[:2]
#     if h > w: img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    
#     # Calculate PPCM using the Calibrator Engine
#     ppcm, dbg, _ = windows_test.calibrator.get_pixels_per_cm(img, t1, t2)
    
#     if ppcm:
#         # 1. Save Local Calibration Settings (Required for persistence)
#         with open(windows_test.CALIBRATION_FILE, 'w') as f:
#             json.dump({"pixels_per_cm": ppcm, "timestamp": str(datetime.now())}, f)
        
#         # NOTE: Cloud sync for calibration is REMOVED as requested.
            
#     # --- RESPONSE TO LOCAL UI ---
#     response_data = {
#         "success": True if ppcm else False, 
#         "pixels_per_cm": ppcm, 
#         # Debug image for Local UI (Base64 JPEG)
#         "debug_image": "data:image/jpeg;base64," + CameraManager.encode_image(dbg),
#         "message": f"Detected: {ppcm:.2f} px/cm" if ppcm else "A4 not found"
#     }

#     # Debug print
#     debug_packet = response_data.copy()
#     debug_packet["debug_image"] = "<Base64_Hidden>"
#     print(f"\n[Server Response] Calibration Packet: {json.dumps(debug_packet, default=str)}")

#     return response_data

@app.post("/api/calibrate")
async def calibrate(t1: int = Form(50), t2: int = Form(150)):
    """Only calculates the PPCM and returns the image. DOES NOT SAVE."""
    if not windows_test.cam_manager: 
        return {"success": False, "message": "Camera not ready"}

    with windows_test.cam_manager.lock:
        img = getattr(windows_test.cam_manager, 'raw_frame', None)
    
    if img is None: 
        return {"success": False, "message": "Camera hardware not ready"}

    h, w = img.shape[:2]
    if h > w: img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    
    # Calculate PPCM using the Calibrator Engine
    ppcm, dbg, _ = windows_test.calibrator.get_pixels_per_cm(img, t1, t2)
            
    # --- RESPONSE TO LOCAL UI (REMOVED SAVING LOGIC FROM HERE) ---
    response_data = {
        "success": True if ppcm else False, 
        "pixels_per_cm": ppcm, 
        # Debug image for Local UI (Base64 JPEG)
        "debug_image": "data:image/jpeg;base64," + CameraManager.encode_image(dbg),
        "message": f"Detected: {ppcm:.2f} px/cm" if ppcm else "A4 not found"
    }

    return response_data

@app.post("/api/calibration/test-a4")
async def test_calibration_a4():
    """
    Online screen's "Test Calibration" step: place a real, plain A4 sheet
    (21.0 x 29.7cm) on the calibrated surface and check whether the ALREADY
    SAVED calibration (from /api/calibration/save) measures it correctly.
    This checks an existing calibration; it does not produce a new one.
    """
    if not windows_test.cam_manager:
        return {"success": False, "message": "Camera not ready"}

    ppcm = windows_test.get_calibration_value()
    if not ppcm or ppcm <= 0:
        return {"success": False, "message": "No saved calibration yet - run Calibrate first."}

    with windows_test.cam_manager.lock:
        img = getattr(windows_test.cam_manager, 'raw_frame', None)

    if img is None:
        return {"success": False, "message": "Camera hardware not ready"}

    h, w = img.shape[:2]
    if h > w:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # A4 paper is a bright, mostly blank rectangle - find it by brightness,
    # not the checkerboard-corner detector /api/calibrate uses.
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return {"success": False, "message": "No sheet detected. Make sure a plain A4 sheet is flat, fully visible, and contrasts with the table."}

    frame_area = h * w
    best_rect = None
    best_area = 0
    for c in contours:
        area = cv2.contourArea(c)
        if area < 0.01 * frame_area or area > 0.9 * frame_area:
            continue  # too small (noise) or too big (background/whole frame)
        rect = cv2.minAreaRect(c)
        rw, rh = rect[1]
        if rw <= 0 or rh <= 0:
            continue
        fill_ratio = area / (rw * rh)
        if fill_ratio < 0.85:
            continue  # not rectangular enough to be a flat sheet
        if area > best_area:
            best_area = area
            best_rect = rect

    if best_rect is None:
        return {"success": False, "message": "Could not find a clear rectangular sheet. Make sure the A4 sheet is flat, fully visible, and contrasts with the table color."}

    rw_px, rh_px = best_rect[1]
    long_px, short_px = max(rw_px, rh_px), min(rw_px, rh_px)

    measured_short_cm = short_px / ppcm
    measured_long_cm = long_px / ppcm
    measured_diag_cm = math.hypot(measured_short_cm, measured_long_cm)

    expected_short_cm, expected_long_cm = 21.0, 29.7
    expected_diag_cm = math.hypot(expected_short_cm, expected_long_cm)

    def pct_err(measured, expected):
        return abs(measured - expected) / expected * 100.0

    err_w = pct_err(measured_short_cm, expected_short_cm)
    err_h = pct_err(measured_long_cm, expected_long_cm)
    err_d = pct_err(measured_diag_cm, expected_diag_cm)

    PASS_THRESHOLD_PCT = 5.0
    passed = max(err_w, err_h, err_d) <= PASS_THRESHOLD_PCT

    return {
        "success": True,
        "passed": passed,
        "message": (
            f"Measured {measured_short_cm:.2f} x {measured_long_cm:.2f}cm vs "
            f"expected 21.0 x 29.7cm ({'within' if passed else 'outside'} "
            f"{PASS_THRESHOLD_PCT:.0f}% tolerance)."
        ),
        "measured": {
            "width_cm": round(measured_short_cm, 2),
            "height_cm": round(measured_long_cm, 2),
            "diagonal_cm": round(measured_diag_cm, 2),
        },
        "expected": {
            "width_cm": expected_short_cm,
            "height_cm": expected_long_cm,
            "diagonal_cm": round(expected_diag_cm, 2),
        },
        "error_percent": {
            "width": round(err_w, 2),
            "height": round(err_h, 2),
            "diagonal": round(err_d, 2),
        },
    }

@app.post("/api/calibration/save")
def save_calibration(req: CalibrationSaveRequest):
    """Triggered ONLY when the user clicks 'Apply'. Saves to JSON safely."""
    calib_data = {}
    # Read existing data to preserve camera settings
    if windows_test.CALIBRATION_FILE.exists():
        try:
            with open(windows_test.CALIBRATION_FILE, 'r') as f:
                calib_data = json.load(f)
        except: pass
        
    calib_data["pixels_per_cm"] = req.pixels_per_cm
    calib_data["timestamp"] = str(datetime.now())
    
    try:
        with open(windows_test.CALIBRATION_FILE, 'w') as f:
            json.dump(calib_data, f, indent=2)
            
        # Update running state in memory
        if hasattr(windows_test, 'app_state'):
            windows_test.app_state["settings"]["pixels_per_cm"] = req.pixels_per_cm
            
        return {"success": True, "message": "Calibration saved permanently."}
    except Exception as e:
        return {"success": False, "message": f"Failed to save: {str(e)}"}

@app.get("/api/reports")
def get_reps(garment_type: Optional[str] = None):
    # This now only fetches LOCAL reports if they exist.
    reps = []
    if windows_test.REPORTS_DIR.exists():
        for f in sorted(os.listdir(windows_test.REPORTS_DIR), reverse=True):
            if f.endswith('.json'):
                try:
                    with open(windows_test.REPORTS_DIR / f) as j:
                        d = json.load(j)
                        if not garment_type or d.get('garment_type') == garment_type: 
                            reps.append(d)
                except: pass
    return reps

@app.get("/api/report/{rid}")
def get_rep_det(rid: str):
    p = windows_test.REPORTS_DIR / f"{rid}.json"
    if not p.exists(): 
        raise HTTPException(404, detail="Report not found")
    
    with open(p) as f: d = json.load(f)
    
    # We no longer save local images, so this part is mostly legacy fallback
    img_path = windows_test.REPORTS_DIR / f"{rid}_measure.jpg"
    if img_path.exists():
        d['measure_image'] = "data:image/jpeg;base64," + CameraManager.encode_image(cv2.imread(str(img_path)))
    return d

# ==========================================
# WI-FI ENDPOINTS (ORIGINAL + NEW)
# ==========================================

@app.get("/api/wifi/status")
async def get_wifi_status():
    """
    NEW: Get current WiFi connection status.
    Returns adapter state, connection status, current SSID, signal strength.
    """
    if not hasattr(windows_test, 'wifi_manager_instance') or not windows_test.wifi_manager_instance:
        return {
            "success": False,
            "status": {
                "adapter_enabled": False,
                "connected": False,
                "ssid": "",
                "signal": 0,
                "state": "ERROR"
            },
            "error": "WiFi Manager not initialized"
        }
    
    try:
        status = windows_test.wifi_manager_instance.get_current_status()
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        print(f"[Error] Status check failed: {e}")
        return {
            "success": False,
            "status": {
                "adapter_enabled": False,
                "connected": False,
                "ssid": "",
                "signal": 0,
                "state": "ERROR"
            },
            "error": str(e)
        }

@app.get("/api/wifi/scan")
def scan_wifi():
    """
    IMPROVED: Scan for available WiFi networks.
    Returns list of networks with current connection status.
    """
    if not hasattr(windows_test, 'wifi_manager_instance') or not windows_test.wifi_manager_instance:
        return {
            "success": False,
            "networks": [],
            "current": {
                "connected": False,
                "ssid": "",
                "signal": 0,
                "adapter_enabled": False
            }
        }
    
    try:
        # Get current status first
        current_status = windows_test.wifi_manager_instance.get_current_status()
        
        # Scan for networks
        networks = windows_test.wifi_manager_instance.scan_networks()
        
        return {
            "success": True,
            "networks": networks,
            "current": {
                "connected": current_status.get("connected", False),
                "ssid": current_status.get("ssid", ""),
                "signal": current_status.get("signal", 0),
                "adapter_enabled": current_status.get("adapter_enabled", True)
            }
        }
    except Exception as e:
        print(f"[Error] Network scan failed: {e}")
        return {
            "success": False,
            "networks": [],
            "current": {
                "connected": False,
                "ssid": "",
                "signal": 0,
                "adapter_enabled": False
            },
            "error": str(e)
        }

@app.post("/api/wifi/connect")
def connect_wifi(creds: WifiConnectRequest):
    """
    Connect to WiFi network with credentials.
    """
    # --- DEBUG: PRINT UI PACKET (INCOMING) ---
    print(f"\n[UI Request] Wi-Fi Connection: SSID={creds.ssid}, Password={'*' * len(creds.password)}")

    if not hasattr(windows_test, 'wifi_manager_instance') or not windows_test.wifi_manager_instance:
        response = {"success": False, "message": "Wi-Fi Manager not initialized"}
    else:
        try:
            response = windows_test.wifi_manager_instance.connect_to_network(creds.ssid, creds.password)
        except Exception as e:
            print(f"[Error] Connection failed: {e}")
            response = {"success": False, "message": f"Connection error: {str(e)}"}
    
    # --- DEBUG: PRINT UI PACKET (OUTGOING) ---
    print(f"[Server Response] Wi-Fi Connect: {response}")

    return response

@app.post("/api/wifi/disconnect")
async def disconnect_wifi():
    """
    NEW: Disconnect from current WiFi network.
    """
    if not hasattr(windows_test, 'wifi_manager_instance') or not windows_test.wifi_manager_instance:
        return {"success": False, "message": "WiFi Manager not initialized"}
    
    try:
        result = windows_test.wifi_manager_instance.disconnect()
        print(f"[Server Response] Wi-Fi Disconnect: {result}")
        return result
    except Exception as e:
        print(f"[Error] Disconnect failed: {e}")
        return {
            "success": False,
            "message": f"Disconnect error: {str(e)}"
        }

@app.post("/api/wifi/toggle")
async def toggle_wifi_adapter(request: ToggleRequest):
    """
    IMPROVED: Enable or disable WiFi adapter.
    REQUIRES ADMINISTRATOR PRIVILEGES.
    """
    if not hasattr(windows_test, 'wifi_manager_instance') or not windows_test.wifi_manager_instance:
        return {"success": False, "message": "WiFi Manager not initialized"}
    
    try:
        print(f"\n[UI Request] Wi-Fi Toggle: state={'ON' if request.state else 'OFF'}")
        
        result = windows_test.wifi_manager_instance.toggle_wifi(request.state)
        
        # Return consistent format
        if result:
            response = {
                "success": True,
                "message": f"WiFi adapter {'enabled' if request.state else 'disabled'}"
            }
        else:
            response = {
                "success": False,
                "message": "Toggle failed. Ensure app is running as Administrator."
            }
        
        print(f"[Server Response] Wi-Fi Toggle: {response}")
        return response
        
    except Exception as e:
        print(f"[Error] Toggle failed: {e}")
        return {
            "success": False,
            "message": f"Toggle error: {str(e)}. Ensure app is running as Administrator."
        }

@app.post("/api/wifi/forget")
async def forget_wifi_network(request: ForgetNetworkRequest):
    """
    NEW: Remove a saved WiFi profile.
    """
    if not hasattr(windows_test, 'wifi_manager_instance') or not windows_test.wifi_manager_instance:
        return {"success": False, "message": "WiFi Manager not initialized"}
    
    try:
        result = windows_test.wifi_manager_instance.forget_network(request.ssid)
        print(f"[Server Response] Wi-Fi Forget: {result}")
        return result
    except Exception as e:
        print(f"[Error] Forget network failed: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }

@app.get("/api/wifi/saved-profiles")
async def get_saved_profiles():
    """
    NEW: Get list of saved WiFi profiles.
    """
    if not hasattr(windows_test, 'wifi_manager_instance') or not windows_test.wifi_manager_instance:
        return {
            "success": False,
            "profiles": [],
            "error": "WiFi Manager not initialized"
        }
    
    try:
        profiles = windows_test.wifi_manager_instance.get_saved_profiles()
        return {
            "success": True,
            "profiles": profiles
        }
    except Exception as e:
        print(f"[Error] Get profiles failed: {e}")
        return {
            "success": False,
            "profiles": [],
            "error": str(e)
        }
    

# ==========================================
# SYSTEM UPDATE ENDPOINTS
# ==========================================

@app.get("/api/system/version")
def get_system_version():
    """
    Reads the encrypted sys_config_v1.bin file and returns the current app version.
    The frontend uses this to check if an update is required.
    """
    current_version = "0.0.0"
    
    if hasattr(windows_test, 'updater') and windows_test.updater:
        try:
            # 1. Get the filename directly from the updater module
            version_file = windows_test.updater.VERSION_FILE
            
            # 2. Safely resolve the absolute path using PROJECT_ROOT
            if hasattr(windows_test, 'PROJECT_ROOT'):
                # PROJECT_ROOT is a pathlib.Path object
                file_path = windows_test.PROJECT_ROOT / version_file
            else:
                file_path = version_file
            
            # 3. Read and decrypt the file using the updater's built-in xor_crypt
            if os.path.exists(str(file_path)):
                with open(file_path, "rb") as f:
                    encrypted_data = f.read()
                    decrypted_data = windows_test.updater.xor_crypt(encrypted_data)
                    # Parse the decrypted JSON to get the version
                    version_data = json.loads(decrypted_data.decode('utf-8'))
                    current_version = version_data.get("version", "0.0.0")
            else:
                print(f"[API Warning] Version file not found at: {file_path}")
                
        except Exception as e:
            print(f"[API Error] Failed to read version file: {e}")
            
    return {"success": True, "version": current_version}


update_status = {
    "state": "idle", # idle, downloading, extracting
    "progress": 0
}

def nextjs_progress_callback(percent):
    update_status["progress"] = percent
    if percent >= 100:
        update_status["state"] = "extracting"

@app.post("/api/system/trigger-update")
async def trigger_update():
    if not hasattr(windows_test, 'updater') or not windows_test.updater:
        return {"status": "error", "message": "Updater module not available."}
   
    update_status["state"] = "downloading"
    update_status["progress"] = 0
    
    # Auto-approve the update prompt since it was triggered manually from the UI
    def auto_approve_update(version):
        return True

    # updater.py automatically spawns a daemon thread when run_in_background=True
    windows_test.updater.check_for_updates(
        ask_user_callback=auto_approve_update,
        run_in_background=True, 
        on_progress=nextjs_progress_callback
    )
    
    return {"status": "started"}

@app.get("/api/system/update-stream")
async def update_stream(request: Request):
  
    async def event_generator():
        while True:
            
            if await request.is_disconnected():
                break
            
            yield f"data: {json.dumps(update_status)}\n\n"
            
            if update_status["state"] == "extracting":
                break
                
            await asyncio.sleep(0.5)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ==========================================
# DEVICE CONFIGURATION ENDPOINTS
# ==========================================

@app.get("/api/system/device-id")
def get_device_id():
    """Returns the current Device ID."""
    current_id = "UNKNOWN_DEVICE"
    if hasattr(windows_test, 'app_state'):
        current_id = windows_test.app_state.get("device_id", "UNKNOWN_DEVICE")
    return {"success": True, "device_id": current_id}

@app.post("/api/system/device-id")
def update_device_id(req: DeviceIDRequest):
    """
    Updates the Device ID in active memory and overrides/creates 
    the device_config.json file.
    """
    new_id = req.device_id.strip()
    if not new_id:
        return {"success": False, "message": "Device ID cannot be empty"}
    
    # 1. Update the active application state
    if hasattr(windows_test, 'app_state'):
        windows_test.app_state["device_id"] = new_id
        
    # 2. Override or create the JSON file locally
    try:
        config_path = windows_test.DEVICE_CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w') as f:
            json.dump({"device_id": new_id}, f, indent=2)
            
        print(f"[System] Device ID updated and saved: {new_id}")
        return {"success": True, "message": f"Device ID updated to {new_id}"}
    except Exception as e:
        print(f"[Error] Failed to save Device ID: {e}")
        return {"success": False, "message": f"Failed to save Device ID: {str(e)}"}
    

# ==========================================
# LINE CONFIGURATION ENDPOINTS
# ==========================================

@app.post("/api/system/select-line")
def select_system_line(req: LineSelectRequest):
    """
    Receives notification from the React app when a production line is selected.
    Saves it to active memory and persistently to disk.
    """
    try:
        line_id = req.line_id.strip()
        line_name = req.line_name.strip() if req.line_name else "Unknown"
        
        if not line_id:
            return {"success": False, "message": "line_id is required"}

        print(f"[API] System Level Line Selection -> Name: {line_name}, ID: {line_id}")

        # 1. Update the active application state
        if hasattr(windows_test, 'app_state'):
            windows_test.app_state['line_id'] = line_id
            windows_test.app_state['line_name'] = line_name
            
        # 2. Persist to file so it survives a reboot
        try:
            config_path = windows_test.LINE_CONFIG_FILE
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump({"line_id": line_id, "line_name": line_name}, f, indent=2)
        except Exception as file_err:
            print(f"[Warning] Failed to save line_config.json: {file_err}")

        return {"success": True, "selected_line": line_id, "line_name": line_name}
        
    except Exception as e:
        print(f"[API Error] Failed to select line: {e}")
        return {"success": False, "message": str(e)}