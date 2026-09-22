import cv2
import numpy as np
import onnxruntime as ort
import os
import sys
import tempfile
import shutil
import atexit

# ==============================================================================
# SECURITY CONFIGURATION
# ==============================================================================
# This key and filename MUST match the ones in secure_builder.py
MODEL_XOR_KEY = 42  
HIDDEN_MODEL_NAME = "sys_core_v1.dll"      # Fake name for .onnx
HIDDEN_DATA_NAME = "sys_core_v1.dll.data"  # Fake name for .data (weights > 2GB)

class ImageProcessor:
    def __init__(self, input_size=(288, 384)):
        self.session = None
        self.input_size = input_size
        self.mean = np.array([0.485, 0.456, 0.406]).astype(np.float32)
        self.std = np.array([0.229, 0.224, 0.225]).astype(np.float32)
        self.temp_dir = None

        try:
            # 1. Determine Base Path (Works for Dev and Frozen EXE)
            if getattr(sys, 'frozen', False):
                # Running as compiled EXE
                base_path = os.path.dirname(sys.executable)
            else:
                # Running as Python Script
                base_path = os.path.dirname(os.path.abspath(__file__))

            # 2. Locate the Encrypted Files (Disguised as DLLs in 'system/libs')
            encrypted_model_path = os.path.join(base_path, "system", "libs", HIDDEN_MODEL_NAME)
            encrypted_data_path = os.path.join(base_path, "system", "libs", HIDDEN_DATA_NAME)

            # Check if encrypted files exist (Production Mode)
            if os.path.exists(encrypted_model_path):
                # print("[SECURE] Found encrypted assets. Decrypting to secure memory...")
                
                # 3. Secure Decryption to Temp Directory
                # We create a temporary folder that will be DELETED when the app closes
                self.temp_dir = tempfile.mkdtemp()
                atexit.register(self._cleanup) # Register cleanup to run on exit

                # Define temp paths (Must use original names so .onnx finds .data)
                temp_model_path = os.path.join(self.temp_dir, "fashion_landmark.onnx")
                
                # Decrypt Main Model
                self._decrypt_file(encrypted_model_path, temp_model_path)
                
                # Decrypt Data File (if it exists)
                if os.path.exists(encrypted_data_path):
                    temp_data_path = os.path.join(self.temp_dir, "fashion_landmark.onnx.data")
                    self._decrypt_file(encrypted_data_path, temp_data_path)

                # 4. Load Model from Temp
                # We force CPU provider to ensure compatibility on all standard PCs
                self.session = ort.InferenceSession(temp_model_path, providers=['CPUExecutionProvider'])
                # print("[AI] Secure Engine Loaded.")

            else:
                # Fallback for Development Mode (Plain .onnx in 'models' folder)
                dev_path = os.path.join(base_path, "models", "fashion_landmark.onnx")
                if os.path.exists(dev_path):
                    print(f"[AI] Dev Mode: Loading plain model from {dev_path}")
                    self.session = ort.InferenceSession(dev_path, providers=['CPUExecutionProvider'])
                else:
                    print(f"[AI Error] Critical: No model found at {encrypted_model_path} or {dev_path}")
                    self.session = None

        except Exception as e:
            print(f"[AI Error] Critical failure during initialization: {e}")
            self._cleanup()
            self.session = None

    def _decrypt_file(self, src, dst):
        """
        Reads encrypted file, applies XOR key using optimized Numpy, writes to temp.
        """
        try:
            # OPTIMIZATION: Use Numpy for fast XOR instead of Python loop
            # Read file as uint8 array directly from disk
            data = np.fromfile(src, dtype=np.uint8)
            
            # Vectorized XOR operation (Instant on CPU)
            data ^= MODEL_XOR_KEY
            
            # Write back to disk (temp folder)
            data.tofile(dst)
            
        except Exception as e:
            print(f"[SECURE] Decryption failed: {e}")
            raise e

    def _cleanup(self):
        """Securely removes temp files when the application closes."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                # print("[SECURE] Temp traces removed.")
            except: 
                pass

    def run_ai_inference(self, image):
        """
        Runs the model on an image and returns keypoints and scores.
        """
        if self.session is None: 
            return [], []
            
        orig_h, orig_w = image.shape[:2]
        input_w, input_h = self.input_size
        
        # Preprocessing
        img_resized = cv2.resize(image, (input_w, input_h))
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        
        # Normalize
        img_data = img_rgb.astype(np.float32) / 255.0
        img_data = (img_data - self.mean) / self.std
        
        # Transpose to (C, H, W)
        img_data = img_data.transpose(2, 0, 1)
        img_data = np.expand_dims(img_data, axis=0)
        
        # Inference
        try:
            input_name = self.session.get_inputs()[0].name
            outputs = self.session.run(None, {input_name: img_data})
            
            heatmaps = outputs[0]
            preds, maxvals = self._get_max_preds(heatmaps)
            
            # Scale coordinates back to original image size
            scale_x = orig_w / heatmaps.shape[3]
            scale_y = orig_h / heatmaps.shape[2]
            preds[:, :, 0] *= scale_x
            preds[:, :, 1] *= scale_y
            
            return preds[0], maxvals[0].flatten()
        except Exception as e:
            print(f"[AI Error] Inference failed: {e}")
            return [], []

    def _get_max_preds(self, batch_heatmaps):
        """
        Get predictions from score maps.
        """
        batch_size = batch_heatmaps.shape[0]
        num_joints = batch_heatmaps.shape[1]
        preds = np.zeros((batch_size, num_joints, 2))
        maxvals = np.zeros((batch_size, num_joints, 1))

        for i in range(batch_size):
            for j in range(num_joints):
                heatmap = batch_heatmaps[i, j]
                _, max_val, _, max_indx = cv2.minMaxLoc(heatmap)
                maxvals[i, j] = max_val
                preds[i, j] = max_indx
        return preds, maxvals