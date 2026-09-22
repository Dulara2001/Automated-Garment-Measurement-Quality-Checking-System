import cv2
import threading
import time
import platform
import numpy as np
import base64

# Try importing Virtual Camera
try:
    import pyvirtualcam
    from pyvirtualcam import PixelFormat
    HAS_VIRTUAL_CAM = True
except ImportError:
    HAS_VIRTUAL_CAM = False
    print("'pyvirtualcam' not found. Virtual Camera output disabled.")

class CameraManager:
    # Default to 2880x2160 (Perfect 4:3 4K)
    def __init__(self, width=2880, height=2160):
        self.VIRTUAL_WIDTH = width
        self.VIRTUAL_HEIGHT = height
        self.IS_WINDOWS = platform.system() == 'Windows'
        
        # State
        self.active_camera_id = 0
        self._camera_explicitly_set = False  # True once set_camera() is called (e.g. from the UI)
        self.rotation_angle = 0
        self.camera_changed = False
        self.running = False
        self.lock = threading.Lock()
        
        self.current_frame = None
        self.last_processed_frame = None
        self.raw_frame = None 
        
        self.process_callback = None
        
        self.cam_stream = None
        self.stream_width = 0
        self.stream_height = 0

        # --- Camera Settings State ---
        self.camera_settings = {
            "brightness": 50,
            "contrast": 50,
            "autofocus": True,
            "focus": 30
        }
        self.settings_pending = False

    @staticmethod
    def encode_image(image):
        if image is None: return ""
        _, buffer = cv2.imencode('.jpg', image)
        return base64.b64encode(buffer).decode('utf-8')

    def list_cameras(self, limit=10):
        available = []
        for i in range(limit):
            if self.IS_WINDOWS:
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(i)
                
            if cap.isOpened():
                # Some external/industrial USB cameras need a few frames to warm up
                # before read() succeeds; a single immediate read can wrongly mark
                # them as unavailable and fall back to the laptop webcam.
                ret = False
                for _ in range(5):
                    ret, _ = cap.read()
                    if ret:
                        break
                    time.sleep(0.1)
                if ret:
                    available.append({"id": i, "name": f"Camera {i}"})
                cap.release()
        return available

    def set_camera(self, camera_id):
        with self.lock:
            self.active_camera_id = camera_id
            self._camera_explicitly_set = True
            self.camera_changed = True

    def _pick_default_camera(self, limit=10):
        """Pick the camera that negotiates the highest resolution.

        DirectShow's device index order is NOT tied to built-in vs external —
        on some machines the external camera enumerates before the laptop
        webcam, on others after. What's reliable for this system is that the
        overhead camera must support high resolution (this engine requests
        3840x2160), while a laptop's built-in webcam is normally capped at
        720p/1080p. So probe each camera's actual negotiated width instead of
        guessing from its index.
        """
        candidates = []
        for i in range(limit):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if self.IS_WINDOWS else cv2.VideoCapture(i)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
            ok = False
            for _ in range(5):
                ok, _ = cap.read()
                if ok:
                    break
                time.sleep(0.1)
            if ok:
                width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                candidates.append((i, width))
            cap.release()

        if not candidates:
            print("Camera auto-select: no camera detected, defaulting to 0")
            return 0

        best_id, best_width = max(candidates, key=lambda c: c[1])
        print(f"Camera auto-select: candidates {candidates}, using camera {best_id} "
              f"({best_width:.0f}px wide)")
        return best_id

    def set_rotation(self, angle):
        with self.lock:
            self.rotation_angle = angle
            
    def get_rotation(self):
        with self.lock:
            return self.rotation_angle

    def set_processor_callback(self, callback_func):
        self.process_callback = callback_func

    def get_latest_frame(self):
        with self.lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None

    def get_processed_frame(self):
        with self.lock:
            if self.last_processed_frame is not None:
                return self.last_processed_frame.copy()
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None

    # def stream_generator(self):
    #     while self.running:
    #         frame = self.get_processed_frame()
    #         if frame is not None:
    #             _, buffer = cv2.imencode('.jpg', frame)
    #             yield (b'--frame\r\n'
    #                    b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
    #         else:
    #             time.sleep(0.05)
    #         time.sleep(0.01)

    def stream_generator(self):
        while self.running:
            # get_processed_frame() returns a COPY. Modifying it here 
            # guarantees the original image remains 100% clean for the AI.
            frame = self.get_processed_frame()
            
            if frame is not None:
                h, w = frame.shape[:2]
                
                # 6% margin on all sides (change 0.06 if you want it wider/narrower)
                margin_percent = 0.04
                margin_x = int(w * margin_percent)
                margin_y = int(h * margin_percent)
                
                # Dynamic scaling to look perfect on any camera resolution (1080p, 4K, etc.)
                thickness = max(3, min(8, int(w * 0.002)))
                font_scale = max(0.5, h / 1440.0)
                
                # Draw the Orange Rectangle
                cv2.rectangle(frame, (margin_x, margin_y), (w - margin_x, h - margin_y), (0, 165, 255), thickness, cv2.LINE_AA)
                

                # Compress and send the frame to the web browser
                _, buffer = cv2.imencode('.jpg', frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            else:
                time.sleep(0.05)
            time.sleep(0.01)

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._engine_loop, daemon=True).start()
            threading.Thread(target=self._console_command_loop, daemon=True).start()

    def _open_camera(self, cam_id):
        if self.IS_WINDOWS:
            cap = cv2.VideoCapture(cam_id, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(cam_id)
            
        # Request maximum 16:9 hardware resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
        
        return cap

    def _apply_hardware_settings(self, cap):
        """Applies Focus directly to the camera lens hardware."""
        if cap is None or not cap.isOpened(): return
        s = self.camera_settings
        
        # 1. Hardware Focus Control
        if s["autofocus"]:
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        else:
            # Force autofocus OFF before sending manual focus values
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            # Apply exact integer focus value for full spectrum camera support
            cap.set(cv2.CAP_PROP_FOCUS, int(s["focus"]))

    def set_camera_controls(self, settings_dict):
        """Receives Brightness/Contrast from UI in real-time"""
        with self.lock:
            self.camera_settings.update(settings_dict)

    def set_focus(self, focus_val, is_auto):
        """Receives Focus commands from UI in real-time"""
        with self.lock:
            self.camera_settings["focus"] = int(focus_val)
            self.camera_settings["autofocus"] = is_auto
            self.settings_pending = True

    def _engine_loop(self):
        if not self._camera_explicitly_set:
            self.active_camera_id = self._pick_default_camera()
        current_id = self.active_camera_id
        cap = self._open_camera(current_id)
        
        # WARM UP BUG FIX: Read 3 blank frames before sending hardware focus commands
        if cap and cap.isOpened():
            for _ in range(3): cap.read()
            self._apply_hardware_settings(cap)
            self.settings_pending = False
        
        print(f"Camera Engine Started on ID: {current_id}")

        while self.running:
            with self.lock:
                if self.camera_changed:
                    new_id = self.active_camera_id
                    temp_cap = self._open_camera(new_id)
                    if temp_cap.isOpened():
                        # Warm up new camera
                        for _ in range(3): temp_cap.read()
                        self._apply_hardware_settings(temp_cap)
                        if cap: cap.release()
                        cap = temp_cap
                        current_id = new_id
                    else:
                        temp_cap.release()
                    self.camera_changed = False

                # Apply Hardware Settings Real-time (Focus)
                if self.settings_pending:
                    self._apply_hardware_settings(cap)
                    self.settings_pending = False
                
                # Copy settings safely to apply software filters below
                s = self.camera_settings.copy()

            ret, frame = cap.read()
            if not ret:
                time.sleep(0.5)
                continue

            # ========================================================
            # GUARANTEED IMAGE FILTERS (Software Processing)
            # Modifies the raw pixels so the AI gets the exact UI look
            # ========================================================
            # Alpha controls Contrast (1.0 is default)
            alpha = s["contrast"] / 50.0 
            # Beta controls Brightness (0 is default, +/- 100 max)
            beta = (s["brightness"] - 50) * 2

            if alpha != 1.0 or beta != 0:
                frame = cv2.convertScaleAbs(frame, alpha=alpha, beta=beta)

            # ========================================================
            # THE ANTI-STRETCH CROP FIX
            # Mathematically crop the 16:9 camera feed to 4:3 
            # ========================================================
            h, w = frame.shape[:2]
            target_aspect = self.VIRTUAL_WIDTH / self.VIRTUAL_HEIGHT 
            current_aspect = w / h
            
            if current_aspect > target_aspect:
                new_w = int(h * target_aspect)
                offset = (w - new_w) // 2
                frame = frame[:, offset:offset+new_w]
            elif current_aspect < target_aspect:
                new_h = int(w / target_aspect)
                offset = (h - new_h) // 2
                frame = frame[offset:offset+new_h, :]

            # Store the perfectly proportioned, filtered frame
            with self.lock:
                self.raw_frame = frame.copy()

            # Ensure exact target resolution
            if frame.shape[1] != self.VIRTUAL_WIDTH or frame.shape[0] != self.VIRTUAL_HEIGHT:
                frame = cv2.resize(frame, (self.VIRTUAL_WIDTH, self.VIRTUAL_HEIGHT))

            # Apply Rotation
            with self.lock:
                angle = self.rotation_angle
            
            if angle == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif angle == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif angle == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

            with self.lock:
                self.current_frame = frame.copy()

            output_frame = frame.copy()
            if self.process_callback:
                try:
                    output_frame = self.process_callback(output_frame)
                except Exception as e:
                    print(f"Processing Error: {e}")

            with self.lock:
                self.last_processed_frame = output_frame.copy()

            self._update_virtual_cam(output_frame)

    def _update_virtual_cam(self, frame):
        if not HAS_VIRTUAL_CAM: return
        h, w = frame.shape[:2]

        if (self.cam_stream is None) or (self.stream_width != w) or (self.stream_height != h):
            if self.cam_stream: self.cam_stream.close()
            try:
                if self.IS_WINDOWS:
                    self.cam_stream = pyvirtualcam.Camera(width=w, height=h, fps=25, 
                                                          backend='unitycapture', fmt=PixelFormat.RGBA)
                else:
                    self.cam_stream = pyvirtualcam.Camera(width=w, height=h, fps=25, 
                                                          fmt=PixelFormat.BGR)
                self.stream_width = w
                self.stream_height = h
            except Exception as e:
                self.cam_stream = None

        if self.cam_stream:
            if self.IS_WINDOWS:
                out = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            else:
                out = frame
            self.cam_stream.send(out)
            self.cam_stream.sleep_until_next_frame()

    def _console_command_loop(self):
        while self.running:
            try:
                user_input = input()
                if user_input.strip().isdigit():
                    self.set_camera(int(user_input))
            except:
                break