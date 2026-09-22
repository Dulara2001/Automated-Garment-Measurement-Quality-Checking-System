import cv2
import numpy as np
import math
import sys
import importlib
import copy
import json
import os
import tempfile
import shutil
import atexit
import traceback
from smart_grid import SmartGridSystem
from trouser_processor import TrouserProcessor
from shirt_processor import ShirtProcessor
from qc_validator import QCValidator

# # ---> NEW: AI Background Removal Imports <---
# try:
#     from rembg import remove, new_session
#     HAS_REMBG = True
# except ImportError:
#     HAS_REMBG = False
#     print("[Warning] rembg not installed. Run: pip install rembg[cpu]")

# ==============================================================================
# CRITICAL FIX: SECURE DISGUISED OFFLINE MODEL LOGIC
# ==============================================================================

# 1. Determine where the disguised model is located based on how the app is running
if getattr(sys, 'frozen', False):
    # Running as PyInstaller EXE: Look in the external system/libs folder
    base_path = os.path.dirname(sys.executable)
    disguised_model_path = os.path.join(base_path, "system", "libs", "sys_bg_v1.dll")
else:
    # Dev mode: Look in the models folder
    base_path = os.path.dirname(os.path.abspath(__file__))
    disguised_model_path = os.path.join(base_path, "models", "u2net.onnx")

# 2. Create a secure, hidden temporary directory
rembg_temp_dir = tempfile.mkdtemp()

# 3. Ensure the temp folder is completely deleted when the app is closed
def cleanup_rembg_temp():
    try:
        shutil.rmtree(rembg_temp_dir)
    except:
        pass
atexit.register(cleanup_rembg_temp)

# 4. FORCE rembg to use this exact temp folder to look for its models 
# (This must happen BEFORE rembg is imported)
os.environ["U2NET_HOME"] = rembg_temp_dir

# 5. Fast-copy the disguised DLL into the temp folder under its real name
if os.path.exists(disguised_model_path):
    temp_u2net_path = os.path.join(rembg_temp_dir, "u2net.onnx")
    shutil.copy2(disguised_model_path, temp_u2net_path)
else:
    print(f"[CRITICAL WARNING] Disguised model NOT FOUND at: {disguised_model_path}")

# ==============================================================================
# AI BACKGROUND REMOVAL IMPORT CATCHING
# ==============================================================================
try:
    from rembg import remove, new_session
    HAS_REMBG = True
except Exception as e:
    HAS_REMBG = False
    print(f"\n[CRITICAL ERROR] rembg completely failed to load!")
    print(f"Exact Error: {e}")
    traceback.print_exc()
    print("[CRITICAL ERROR END]\n")

class MeasurementEngine:
    def __init__(self):
        # Register available processors
        self.processors = {
            'trousers': TrouserProcessor(),
            'short_sleeve_top': ShirtProcessor(),
            'shirt': ShirtProcessor(),
            't-shirt': ShirtProcessor(),
            'top': ShirtProcessor(),
            # Future expansion hooks
            'long_sleeve_top': ShirtProcessor(),
            'trouser_short': TrouserProcessor(),
            # Back view of trousers, used to capture Back Rise (customer POM K-05).
            'trousers_back': TrouserProcessor()
        }
        # Initialize the QC Validator
        # tolerance_cm=1.0 is the default fallback if specific tolerances are missing in JSON
        self.validator = QCValidator(tolerance_cm=1.0)
        self.last_warnings = []   # safety-check results for the most recent process() call
        
        # ---> NEW: Initialize the AI Background Removal session (U-Net) <---
        if HAS_REMBG:
            self.bg_session = new_session("u2net")
        else:
            self.bg_session = None

    def reload_config(self):
        """Reloads config file to apply changes immediately"""
        if 'garment_config' in sys.modules:
            importlib.reload(sys.modules['garment_config'])
        import garment_config
        return garment_config

    def refine_mask_background(self, color_image, mask):
        """
        [TROUSER OUTLINE FIX] Remove table-coloured pixels from the U2-Net outline.

        U2-Net runs at 320x320 (inside rembg) and on real station photos it filled in the gap
        between the legs, turning the trousers into one solid shape. The table visible between the
        legs has a very different colour from the garment, so it can be carved back out.

        Safe by design: returns the original mask unchanged when the garment and table colours
        are too similar to separate, or when carving would remove too much.
        """
        try:
            h, w = mask.shape[:2]
            if not (mask > 127).any():
                return mask
            lab = cv2.cvtColor(color_image, cv2.COLOR_BGR2LAB).astype(np.float32)
            big = max(h, w)
            m = (mask > 127).astype(np.uint8)

            # Background colour: a ring just outside the garment (the table, not the room)
            k_in = np.ones((max(3, int(0.01 * big)),) * 2, np.uint8)
            k_out = np.ones((max(5, int(0.04 * big)),) * 2, np.uint8)
            ring = (cv2.dilate(m, k_out) > 0) & ~(cv2.dilate(m, k_in) > 0)
            core = cv2.erode(m, np.ones((max(3, int(0.02 * big)),) * 2, np.uint8)) > 0
            if ring.sum() < 500 or core.sum() < 500:
                return mask
            bg = np.median(lab[ring], axis=0)
            fg = np.median(lab[core], axis=0)
            contrast = float(np.linalg.norm(fg - bg))
            if contrast < 25.0:
                return mask                         # garment too close to table colour

            d_bg = np.linalg.norm(lab - bg, axis=2)
            d_fg = np.linalg.norm(lab - fg, axis=2)
            table_like = (d_bg < max(12.0, 0.35 * contrast)) & (d_bg < d_fg)

            carved = ((m > 0) & ~table_like).astype(np.uint8) * 255
            carved = cv2.morphologyEx(carved, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            carved = cv2.morphologyEx(carved, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

            contours, _ = cv2.findContours(carved, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return mask
            out = np.zeros_like(mask)
            cv2.drawContours(out, [max(contours, key=cv2.contourArea)], -1, 255, -1)   # fills holes

            before, after = float((mask > 127).sum()), float((out > 127).sum())
            if after < 0.70 * before:
                return mask                         # carved too much: don't trust it
            return out
        except Exception as e:
            print(f"[Warning] refine_mask_background skipped: {e}")
            return mask

    def check_trouser_capture(self, mask, averaged_data, g_config, active_keys, code_to_name,
                              processor_warnings, pixels_per_cm):
        """
        Returns [{'level': 'retake'|'info', 'message': str}, ...].
        'retake' means the numbers cannot be trusted and the garment must not PASS.
        """
        warnings = []

        def add(level, message):
            if not any(w['message'] == message for w in warnings):
                warnings.append({'level': level, 'message': message})

        h, w = mask.shape[:2]
        ys, xs = np.where(mask > 127)

        # 1. Nothing found
        if len(xs) == 0:
            add('retake', "No garment found in the photo.")
            return warnings

        # 2. Cut off at the edge of the photo
        border = max(3, int(0.004 * max(h, w)))
        touching = []
        if ys.min() <= border:
            touching.append("top")
        if ys.max() >= h - 1 - border:
            touching.append("bottom")
        if xs.min() <= border:
            touching.append("left")
        if xs.max() >= w - 1 - border:
            touching.append("right")
        if touching:
            add('retake', "Garment is cut off at the " + " and ".join(touching) +
                " edge of the photo. Move it fully into view and retake.")

        # 3. Not trousers: trousers have a clear gap between the legs
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        outline = max(contours, key=cv2.contourArea)
        bx, by, bw, bh = cv2.boundingRect(outline)
        deepest = 0.0
        try:
            hull = cv2.convexHull(outline, returnPoints=False)
            defects = cv2.convexityDefects(outline, hull)
            if defects is not None:
                for _, _, f, depth in defects[:, 0]:
                    px, py = outline[f][0]
                    if bx + 0.25 * bw < px < bx + 0.75 * bw:
                        deepest = max(deepest, depth / 256.0)
        except cv2.error:
            pass
        if deepest < 0.15 * bh:
            add('retake', "This does not look like trousers (no clear gap between the legs). "
                          "Check the garment type and that the legs are laid out flat.")

        # 4. Upside down: the waistband should be above the hems
        by_code = {d['code']: d for d in averaged_data}
        hem = by_code.get('K') or by_code.get('L')
        if 'J' in by_code and hem is not None:
            waist_y = (by_code['J']['coords']['p1'][1] + by_code['J']['coords']['p2'][1]) / 2
            hem_y = (hem['coords']['p1'][1] + hem['coords']['p2'][1]) / 2
            if waist_y > hem_y:
                add('retake', "Garment appears to be upside down (waistband below the hems). "
                              "Turn it so the waistband is at the top and retake.")

        # 5. Proportions: catch measuring lines that landed on the wrong edges.
        #    Flat trousers: hip is always wider than the waist, and one thigh is narrower than the hip.
        def val(code):
            d = by_code.get(code)
            return float(d['px']) if d and d.get('px') else None
        waist_px, hip_px, thigh_px = val('J'), val('M'), val('T')
        if waist_px and hip_px and hip_px < 0.9 * waist_px:
            add('retake', "Waist and hip do not match (hip narrower than waist). "
                          "The measuring points probably landed on the wrong edges - check the photo and retake.")
        if hip_px and thigh_px and not (0.35 * hip_px <= thigh_px <= 0.9 * hip_px):
            add('retake', "Thigh does not match the hip width. Check the legs are laid flat and retake.")

        # 6. Missing measurements must not silently PASS
        defined = {m[2].strip().upper() for m in g_config['measurements']}
        expected = [k for k in active_keys if k in defined] if active_keys else sorted(defined)
        measured = {d['code'].strip().upper() for d in averaged_data}
        missing = [k for k in expected if k not in measured]
        optional = {str(c).upper() for c in getattr(self, '_optional_codes', [])}
        required_missing = [k for k in missing if k not in optional]
        if required_missing:
            names = ", ".join(f"{code_to_name.get(k, k)} ({k})" for k in required_missing)
            add('retake', f"Could not measure: {names}.")

        # 7. Notes from the processor (crotch alignment, fly stitch, thigh fallback)
        for pw in processor_warnings or []:
            add(pw.get('level', 'info'), pw['message'])

        return warnings

    def get_clean_edges(self, pre_blurred_image, t1, t2):
        """
        OPTIMIZED: Uses the pre-calculated bilateral filter image.
        Keeps edges sharp but removes noise.
        """
        # Canny Edge Detection on the pre-filtered image
        edges = cv2.Canny(pre_blurred_image, t1, t2)
        
        # Morphological Close: Fills small gaps
        kernel = np.ones((5,5), np.uint8)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        
        # Find Contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        clean_edges = np.zeros_like(edges)
        
        # Filter: Ignore small shapes
        for cnt in contours:
            if cv2.contourArea(cnt) > 500: 
                cv2.drawContours(clean_edges, [cnt], -1, 255, 1)
                
        return clean_edges

    def get_solid_mask(self, blurred_gray, t1=100, t2=200):
        """
        BUGFIX: get_solid_mask_ai() fell back to this method when rembg was unavailable, but
        it did not exist, so a missing rembg raised AttributeError instead of degrading.

        Classic (non-AI) silhouette: edges -> close -> fill the largest contour.
        Less accurate than U^2-Net, so it is only a safety net.
        """
        edges = cv2.Canny(blurred_gray, t1, t2)
        kernel = np.ones((5, 5), np.uint8)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        final_mask = np.zeros_like(edges)
        if contours:
            largest_cnt = max(contours, key=cv2.contourArea)
            cv2.drawContours(final_mask, [largest_cnt], -1, 255, -1)
        return final_mask

    def get_solid_mask_ai(self, color_image):
        """
        THE GOLD STANDARD: Uses U^2-Net AI to perfectly extract the garment silhouette.
        SPEED UPGRADE: Downscales for the neural net, then upscales the mask. 
        Saves massive processing time without losing the shape or affecting edge accuracy.
        """
        if not HAS_REMBG or self.bg_session is None:
            # Fallback to the old method if the library isn't installed
            gray = cv2.cvtColor(color_image, cv2.COLOR_BGR2GRAY)
            blurred = cv2.bilateralFilter(gray, 9, 75, 75)
            return self.get_solid_mask(blurred, 100, 200)

        h, w = color_image.shape[:2]
        
        # --- SPEED HACK: Shrink image ONLY for the AI ---
        # 720p height is the sweet spot for U-Net accuracy vs speed
        scale = 720.0 / h
        new_w, new_h = int(w * scale), 720
        small_img = cv2.resize(color_image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # 1. Ask the AI to generate a mask (Lightning Fast now)
        small_mask = remove(small_img, session=self.bg_session, only_mask=True)
        
        # 2. Scale the perfect mask back up to your exact 4K size
        ai_mask = cv2.resize(small_mask, (w, h), interpolation=cv2.INTER_NEAREST)
        
        # 3. Threshold just to ensure it is strictly 0 (black) and 255 (white)
        _, binary_mask = cv2.threshold(ai_mask, 127, 255, cv2.THRESH_BINARY)
        
        # 4. Very light cleanup (Removes tiny specs of dust the AI might have caught)
        kernel = np.ones((3, 3), np.uint8)
        clean_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        
        # 5. Grab only the largest shape (Guarantees we only get the shirt, not hands or table debris)
        contours, _ = cv2.findContours(clean_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        final_mask = np.zeros_like(clean_mask)
        
        if contours:
            largest_cnt = max(contours, key=cv2.contourArea)
            # Draw the silhouette solid white
            cv2.drawContours(final_mask, [largest_cnt], -1, 255, -1)
                
        return final_mask
    
    def to_mixed_fraction(self, decimal_val, denominator=16):
        """Converts a decimal to a rounded mixed fraction string and float."""
        import math
        rounded_val = round(decimal_val * denominator) / denominator
        whole = int(rounded_val)
        remainder = int(round((rounded_val - whole) * denominator))
        
        if remainder == 0:
            return rounded_val, f"{whole}"
        elif remainder == denominator:
            return rounded_val, f"{whole + 1}"
        
        gcd = math.gcd(remainder, denominator)
        num = remainder // gcd
        den = denominator // gcd
        
        if whole == 0:
            return rounded_val, f"{num}/{den}"
        else:
            return rounded_val, f"{whole} {num}/{den}"

    def classify_size(self, measurements, garment_type, size_standards, config_module=None):
        """Identifies the best size using a 'Weighted Voting System'."""
        file_unit = size_standards.get("units", "cm")
        
        if garment_type not in size_standards:
             return "Unknown", 0, {}

        raw_std_entry = size_standards[garment_type]
        if 'sizes' in raw_std_entry:
            size_map = raw_std_entry['sizes']
        else:
            size_map = raw_std_entry

        if not size_map: return "Unknown", 0, {}
        
        active_keys = []
        if config_module:
            raw_keys = config_module.KEY_MEASUREMENTS.get(garment_type, [])
            active_keys = [str(k).strip().upper() for k in raw_keys if k is not None]
        
        # SAFE FALLBACK: Parses fraction strings or decimal strings safely
        measured_map = {m.get('code', m['name']): self.validator.parse_value(str(m['value']), source_unit="inch") for m in measurements}
        candidates = []

        for size_name, raw_specs in size_map.items():
            weighted_score = 0
            raw_matches = 0
            total_deviation = 0
            comparisons_made = 0
            possible_score = 0
            
            if isinstance(raw_specs, list):
                for item in raw_specs:
                    code = item.get('description', 'Unknown').strip()
                    
                    if code in measured_map:
                        weight = 1
                        if active_keys and code.upper() in active_keys:
                            weight = 3 
                        possible_score += weight
                        
                        target_val = self.validator.parse_value(item.get('value', 0), file_unit)
                        
                        raw_t_plus = item.get('tol_plus', self.validator.default_tolerance)
                        raw_t_minus = item.get('tol_minus', raw_t_plus)
                        
                        t_plus = abs(self.validator.parse_value(raw_t_plus, file_unit))
                        t_minus = abs(self.validator.parse_value(raw_t_minus, file_unit))
                        
                        actual_val = measured_map[code]
                        deviation = abs(actual_val - target_val)
                        
                        lower_limit = target_val - t_minus
                        upper_limit = target_val + t_plus
                        
                        if lower_limit <= actual_val <= upper_limit:
                            weighted_score += weight
                            raw_matches += 1
                        
                        total_deviation += deviation
                        comparisons_made += 1
            
            if comparisons_made > 0:
                candidates.append({
                    'size': size_name,
                    'score': weighted_score,
                    'matches': raw_matches,
                    'avg_dev': total_deviation / comparisons_made,
                    'max_possible': possible_score
                })

        if not candidates: return "Unknown", 0, {}
        candidates.sort(key=lambda x: (-x['score'], x['avg_dev']))
        best = candidates[0]
        if best['max_possible'] > 0:
            confidence = (best['score'] / best['max_possible']) * 100
        else:
            confidence = 0
        return best['size'], confidence, {}

    def to_mixed_fraction(self, decimal_val, denominator=16):
        """Converts a decimal to a rounded mixed fraction string and float."""
        import math
        rounded_val = round(decimal_val * denominator) / denominator
        whole = int(rounded_val)
        remainder = int(round((rounded_val - whole) * denominator))
        
        if remainder == 0:
            return rounded_val, f"{whole}"
        elif remainder == denominator:
            return rounded_val, f"{whole + 1}"
        
        gcd = math.gcd(remainder, denominator)
        num = remainder // gcd
        den = denominator // gcd
        
        if whole == 0:
            return rounded_val, f"{num}/{den}"
        else:
            return rounded_val, f"{whole} {num}/{den}"

    def process(self, image_input, keypoints_input, scores_input, pixels_per_cm, 
                manual_garment_type="trousers", size_standards=None, thresh_val=100,
                fixed_crotch_point=None): 
        
        config_module = self.reload_config()
        if size_standards is None:
            size_standards = config_module.SIZE_STANDARDS

        g_type = manual_garment_type.lower() if manual_garment_type else "trousers"
        if g_type in ['shirt', 't-shirt', 'top']: 
            g_type = 'short_sleeve_top'

        # --- 1. HANDLE BURST FRAMES ---
        if isinstance(image_input, list):
            images = image_input
            all_kps = keypoints_input
            all_scores = scores_input
        else:
            images = [image_input]
            all_kps = [keypoints_input]
            all_scores = [scores_input]

        num_frames = len(images)
        mid_idx = num_frames // 2 if num_frames > 0 else 0
        
        # Base image for mask generation (use middle frame)
        base_proc_img = images[mid_idx].copy()
        h, w = base_proc_img.shape[:2]

        g_config = config_module.GARMENT_CONFIG.get(g_type, config_module.GARMENT_CONFIG.get('trousers'))
        logic_map = g_config['point_logic']
        zone_rules = g_config.get('zone_config', {})
        left_zone = zone_rules.get('left_zone', [])
        right_zone = zone_rules.get('right_zone', [])
        garment_proc = self.processors.get(g_type, self.processors['trousers'])

        # --- DYNAMIC NAME MAPPER ---
        code_to_name = {}
        if g_type in size_standards:
            sz_data = size_standards[g_type]
            sizes_dict = sz_data.get('sizes', sz_data) if isinstance(sz_data, dict) else {}
            if sizes_dict:
                first_size = list(sizes_dict.values())[0]
                if isinstance(first_size, list):
                    for item in first_size:
                        c = item.get('description', '').strip()
                        n = item.get('name', c)
                        if c: code_to_name[c] = n

        raw_std_entry = size_standards.get(g_type, {})
        size_map = raw_std_entry.get('sizes', raw_std_entry) if isinstance(raw_std_entry, dict) else {}
        actual_sizes = {k: v for k, v in size_map.items() if isinstance(v, list)}
        is_single_size = (len(actual_sizes) == 1)
        shift_val_in = 1.0 
        target_shoulder_width_in = 0.0 
        
        if is_single_size:
            only_size_measurements = list(actual_sizes.values())[0]
            for item in only_size_measurements:
                desc = item.get('description', '').strip()
                name_str = item.get('name', '').strip()
                if desc == 'I' or name_str == 'CPSC - Upper Arm Position - 2 Piece':
                    try: shift_val_in = float(item.get('value', 1.0))
                    except ValueError: pass
                elif desc == 'H' or name_str == 'Shoulder Width':
                    try: target_shoulder_width_in = float(item.get('value', 0.0))
                    except ValueError: pass

        raw_keys = config_module.KEY_MEASUREMENTS.get(g_type, [])
        # BUGFIX: match codes case-insensitively. data/size_standards.json listed "k", which
        # silently removed Left Leg Opening ("K") from every trouser result.
        active_keys = [str(k).strip().upper() for k in raw_keys if k is not None]

        # --- PRE-CALCULATE DUPLICATE CODES FOR (L)/(R) LOGIC ---
        code_counts = {}
        for p1, p2, code in g_config['measurements']:
            c = code.strip()
            code_counts[c] = code_counts.get(c, 0) + 1

        # =======================================================
        # 1. RUN REMBG AI ONLY ONCE (Saves massive time)
        # =======================================================
        garment_mask = self.get_solid_mask_ai(base_proc_img)
        if (g_type in ('trousers', 'trousers_back', 'trouser_short')
                and getattr(config_module, 'TROUSER_MASK_REFINE', False)):
            garment_mask = self.refine_mask_background(base_proc_img, garment_mask)

        frames_data = []

        # =======================================================
        # 2. RUN EDGE DETECTION & REFINEMENT 3 TIMES
        # =======================================================
        for f_idx in range(num_frames):
            proc_img = images[f_idx].copy()
            kps = all_kps[f_idx]
            scores = all_scores[f_idx]

            # Clear shapes so the garment processor starts clean for this pass
            if hasattr(garment_proc, 'debug_shapes'):
                garment_proc.debug_shapes = []

            gray = cv2.cvtColor(proc_img, cv2.COLOR_BGR2GRAY)
            blurred_heavy = cv2.bilateralFilter(gray, 15, 75, 75) 
            edge_map = self.get_clean_edges(blurred_heavy, thresh_val, 200)

            grid = SmartGridSystem(w, h)
            valid_kps = {}
            invalid_kps = []
            
            for i, kp in enumerate(kps):
                score = scores[i] if scores is not None and len(scores) > i else 1.0
                if score > 0.1 and 0 < kp[0] < w and 0 < kp[1] < h:
                    x, y = int(kp[0]), int(kp[1])
                    is_valid, msg = grid.validate_point_location(x, y, i, zone_rules)
                    if not is_valid: invalid_kps.append((x, y))
                    else: valid_kps[i] = (x, y)

            try:
                valid_kps = garment_proc.adjust_points(kps, valid_kps, fixed_crotch_point)
            except TypeError:
                valid_kps = garment_proc.adjust_points(kps, valid_kps)

            # [PANT POMs] Find the real crotch (the red dot is only a cross-check) and hand the
            # processor the colour frame for fly-stitch detection.
            if hasattr(garment_proc, 'set_color_frame'):
                garment_proc.set_color_frame(proc_img)
            if (hasattr(garment_proc, 'refine_crotch')
                    and getattr(config_module, 'TROUSER_CROTCH_MODE', 'fixed_dot') == 'auto'):
                valid_kps = garment_proc.refine_crotch(valid_kps, garment_mask, pixels_per_cm)

            frame_measurements = {}

            for m_idx, (p1_data, p2_data, internal_code) in enumerate(g_config['measurements']):
                clean_code = internal_code.strip()
                if active_keys and clean_code.upper() not in active_keys: continue
                display_name = code_to_name.get(clean_code, clean_code)
                
                # --- SMART (L) and (R) APPEND LOGIC (SPATIAL ZONE BASED) ---
                if code_counts.get(clean_code, 0) > 1:
                    pts_to_check = []
                    for p_data in [p1_data, p2_data]:
                        if isinstance(p_data, list): pts_to_check.extend(p_data)
                        elif isinstance(p_data, int): pts_to_check.append(p_data)
                        elif isinstance(p_data, dict):
                            if 'base' in p_data:
                                b = p_data['base']
                                if isinstance(b, list): pts_to_check.extend(b)
                                elif isinstance(b, int): pts_to_check.append(b)
                            if 'upper_arm_parallel' in p_data:
                                s = p_data['upper_arm_parallel'].get('sleeve_top_pt')
                                if isinstance(s, list): pts_to_check.extend(s)
                                elif isinstance(s, int): pts_to_check.append(s)

                    is_left = any(pt in left_zone for pt in pts_to_check)
                    is_right = any(pt in right_zone for pt in pts_to_check)

                    if is_right and not is_left and '(r)' not in display_name.lower():
                        display_name += " (R)"
                    elif is_left and not is_right and '(l)' not in display_name.lower():
                        display_name += " (L)"
                
                p1_eval = copy.deepcopy(p1_data)
                p2_eval = copy.deepcopy(p2_data)
                
                is_upper_arm = False
                if isinstance(p1_eval, dict) and 'upper_arm_parallel' in p1_eval: is_upper_arm = True
                elif isinstance(p2_eval, dict) and 'upper_arm_parallel' in p2_eval: is_upper_arm = True
                    
                if is_upper_arm:
                    if not is_single_size: continue 
                    if isinstance(p1_eval, dict) and 'upper_arm_parallel' in p1_eval:
                        p1_eval['upper_arm_parallel']['shift_in'] = shift_val_in
                    if isinstance(p2_eval, dict) and 'upper_arm_parallel' in p2_eval:
                        p2_eval['upper_arm_parallel']['shift_in'] = shift_val_in

                if isinstance(p1_eval, dict) and 'dynamic_left_shoulder' in p1_eval:
                    p1_eval['dynamic_left_shoulder']['target_width_in'] = target_shoulder_width_in
                if isinstance(p2_eval, dict) and 'dynamic_left_shoulder' in p2_eval:
                    p2_eval['dynamic_left_shoulder']['target_width_in'] = target_shoulder_width_in

                try:
                    p1_fin = garment_proc.get_final_point_location(p1_eval, valid_kps, gray, pixels_per_cm, logic_map, mask=garment_mask)
                    p2_fin = garment_proc.get_final_point_location(p2_eval, valid_kps, gray, pixels_per_cm, logic_map, mask=garment_mask)
                except TypeError:
                    p1_fin = garment_proc.get_final_point_location(p1_eval, valid_kps, gray, pixels_per_cm, logic_map)
                    p2_fin = garment_proc.get_final_point_location(p2_eval, valid_kps, gray, pixels_per_cm, logic_map)

                if p1_fin is not None and p2_fin is not None:
                    # Use m_idx to ensure unique saving (fixes the overwrite bug!)
                    frame_measurements[m_idx] = {
                        "raw_code": clean_code, "name": display_name, "p1": p1_fin, "p2": p2_fin
                    }

            frame_debug_shapes = copy.deepcopy(getattr(garment_proc, 'debug_shapes', []))
            frame_warnings = copy.deepcopy(getattr(garment_proc, 'warnings', []))

            frames_data.append({
                "proc_img": proc_img,
                "valid_kps": valid_kps,
                "invalid_kps": invalid_kps,
                "measurements": frame_measurements,
                "debug_shapes": frame_debug_shapes,
                "warnings": frame_warnings,
                "edge_map": edge_map
            })

        if not frames_data:
            empty_img = base_proc_img if num_frames > 0 else np.zeros((100, 100, 3), dtype=np.uint8)
            return empty_img, empty_img, empty_img, empty_img, empty_img, empty_img, [], "Unknown", 0, {}

# =======================================================
        # 3. AVERAGE ALL 3 DETECTED RUNS
        # =======================================================
        averaged_data = []
        temp_draw_list = []

        file_unit = size_standards.get("units", "cm").lower() if size_standards else "cm"
        unit_mode = size_standards.get("mode", "decimal").lower() if size_standards else "decimal"
        
        # Determine if we are using mixed fractions and set the correct denominator (16 for inch, 10 for cm)
        is_mixed_mode = (unit_mode == "mixed" and pixels_per_cm > 0)
        fraction_denominator = 16 if file_unit == "inch" else 10

        # Iterate via m_idx to guarantee we catch every single unique measurement
        for m_idx, (_, _, internal_code) in enumerate(g_config['measurements']):
            clean_code = internal_code.strip()
            if active_keys and clean_code.upper() not in active_keys: continue

            sum_p1_x, sum_p1_y = 0, 0
            sum_p2_x, sum_p2_y = 0, 0
            valid_count = 0
            disp_name = ""

            for fd in frames_data:
                if m_idx in fd["measurements"]:
                    m = fd["measurements"][m_idx]
                    sum_p1_x += m["p1"][0]
                    sum_p1_y += m["p1"][1]
                    sum_p2_x += m["p2"][0]
                    sum_p2_y += m["p2"][1]
                    disp_name = m["name"]
                    valid_count += 1

            if valid_count > 0:
                avg_p1 = (int(sum_p1_x / valid_count), int(sum_p1_y / valid_count))
                avg_p2 = (int(sum_p2_x / valid_count), int(sum_p2_y / valid_count))

                dist_px = math.sqrt((avg_p1[0]-avg_p2[0])**2 + (avg_p1[1]-avg_p2[1])**2)
                dist_cm = dist_px / pixels_per_cm if pixels_per_cm > 0 else 0
                raw_inch_val = dist_cm / 2.54 if pixels_per_cm > 0 else dist_px
                
                # Dynamic unit selection
                if pixels_per_cm > 0:
                    if file_unit == "inch":
                        target_val = raw_inch_val
                        unit_label = "in"
                    else:
                        target_val = dist_cm
                        unit_label = "cm"
                else:
                    target_val = dist_px
                    unit_label = "px"
                
                decimal_str = f"{target_val:.2f}" if pixels_per_cm > 0 else f"{dist_px:.0f}"
                
                if pixels_per_cm > 0:
                    fraction_float, fraction_str = self.to_mixed_fraction(target_val, fraction_denominator)
                else:
                    fraction_float, fraction_str = dist_px, f"{dist_px:.0f}"
                
                if is_mixed_mode:
                    final_val = fraction_float 
                    val_str = fraction_str
                else:
                    final_val = target_val
                    val_str = decimal_str
                
                data_entry = {
                    "code": clean_code, 
                    "name": disp_name, 
                    "value": val_str,               
                    "value_decimal": decimal_str,   
                    "value_fraction": fraction_str, 
                    "unit": unit_label, "status": "INFO", "px": dist_px,
                    "coords": {"p1": avg_p1, "p2": avg_p2}
                }
                averaged_data.append(data_entry)

                temp_draw_list.append({
                    "p1": avg_p1, "p2": avg_p2, "val": final_val, 
                    "str_val": val_str, "name": disp_name, "px_val": dist_px,
                    "data_ref": data_entry, "raw_code": clean_code
                })
                
        # =======================================================
        # 4. QC AND STANDARDS CLASSIFICATION
        # =======================================================
        size, conf, suggestions = self.classify_size(averaged_data, g_type, size_standards, config_module)
        qc_results = []
        if size != "Unknown" and size_standards:
            _, qc_results, _ = self.validator.validate_against_size_standard(averaged_data, size, size_standards, g_type)
        
        # --- THE COLOR BUG FIX: LINK QC BY UNIQUE NAME + CODE ---
        # This completely separates (R) and (L) so they get colored independently
        qc_indexed_lookup = {f"{res['code']}_{res['name']}": res['status'] for res in qc_results}

        standards_lookup = {}
        if size != "Unknown" and size_standards and g_type in size_standards:
            size_data = size_standards[g_type].get('sizes', size_standards[g_type])
            if size in size_data:
                for std in size_data[size]:
                    code_key = std.get('description', '').strip()
                    raw_target = std.get('value', '-')
                    raw_t_plus = std.get('tol_plus', '-')
                    raw_t_minus = std.get('tol_minus', '-')
                    
                    if is_mixed_mode and raw_target != '-':
                        try:
                            # Note: parse_value no longer forces "inch" conversions
                            parsed_t = self.validator.parse_value(raw_target)
                            parsed_tp = self.validator.parse_value(raw_t_plus)
                            parsed_tm = self.validator.parse_value(raw_t_minus)
                            _, raw_target = self.to_mixed_fraction(parsed_t, fraction_denominator)
                            _, raw_t_plus = self.to_mixed_fraction(parsed_tp, fraction_denominator)
                            _, raw_t_minus = self.to_mixed_fraction(parsed_tm, fraction_denominator)
                        except Exception:
                            pass

                    standards_lookup[code_key] = {"target_value": raw_target, "tol_plus": raw_t_plus, "tol_minus": raw_t_minus}
        
        for d in averaged_data:
            m_code = d.get('code')
            if m_code in standards_lookup:
                d['target_value'] = standards_lookup[m_code]['target_value']
                d['tol_plus'] = standards_lookup[m_code]['tol_plus']
                d['tol_minus'] = standards_lookup[m_code]['tol_minus']
            else:
                d['target_value'] = '-'; d['tol_plus'] = '-'; d['tol_minus'] = '-'

        # =======================================================
        # 5. DRAW ON THE SINGLE MIDDLE FRAME
        # =======================================================
        base_res = frames_data[mid_idx] # Draw on the middle frame

        proc_img_final = base_res['proc_img']
        grid = SmartGridSystem(w, h)
        img_detect = grid.draw_grid_on_image(proc_img_final.copy())
        img_measure = proc_img_final.copy() 
        overlay_detect = np.zeros((h, w, 4), dtype=np.uint8)
        overlay_measure = np.zeros((h, w, 4), dtype=np.uint8)

        for i, (x, y) in base_res['valid_kps'].items():
            cv2.circle(img_detect, (x, y), 15, (0, 0, 255), -1)
            cv2.circle(img_detect, (x, y), 20, (255, 255, 255), 4)
            label = str(i)
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 3)
            bx, by = x + 25, y - 25
            cv2.rectangle(img_detect, (bx, by - text_h - 10), (bx + text_w + 10, by + 10), (0, 0, 0), -1)
            cv2.putText(img_detect, label, (bx + 5, by), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3, cv2.LINE_AA)
            
            cv2.circle(overlay_detect, (x, y), 15, (0, 0, 255, 255), -1)
            cv2.circle(overlay_detect, (x, y), 20, (255, 255, 255, 255), 4)
            cv2.rectangle(overlay_detect, (bx, by - text_h - 10), (bx + text_w + 10, by + 10), (0, 0, 0, 255), -1)
            cv2.putText(overlay_detect, label, (bx + 5, by), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255, 255), 3, cv2.LINE_AA)

        for (x, y) in base_res['invalid_kps']:
            cv2.circle(img_detect, (x, y), 20, (0, 0, 255), 4)
            cv2.circle(overlay_detect, (x, y), 20, (0, 0, 255, 255), 4)

        for item in temp_draw_list:
            # Use Unique Key to fetch correct QC status
            unique_qc_key = f"{item['raw_code']}_{item['name']}"
            status = qc_indexed_lookup.get(unique_qc_key, "INFO")
            item['data_ref']['status'] = status
            
            line_color = (0, 255, 255); text_color = (0, 255, 255)
            if status == "PASS": line_color = (0, 255, 0); text_color = (0, 255, 0)
            elif status == "FAIL": line_color = (0, 0, 255); text_color = (0, 0, 255)
            
            line_bgra = (*line_color, 255); text_bgra = (*text_color, 255)
            marker_bgra = (0, 255, 0, 255); black_bgra = (0, 0, 0, 255)

            p1 = item['p1']; p2 = item['p2']
            mid_x = (p1[0] + p2[0]) // 2; mid_y = (p1[1] + p2[1]) // 2
            
            # Dynamic text label pulling 'in' or 'cm' directly from the data
            unit_lbl = item['data_ref']['unit']
            text = f"{item['str_val']}{unit_lbl}" if unit_lbl != "px" else f"{item['px_val']:.0f}px"
            
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 3)
            
            cv2.drawMarker(img_measure, p1, (0, 255, 0), cv2.MARKER_CROSS, 40, 5)
            cv2.drawMarker(img_measure, p2, (0, 255, 0), cv2.MARKER_CROSS, 40, 5)
            cv2.line(img_measure, p1, p2, line_color, 4)
            cv2.rectangle(img_measure, (mid_x-5, mid_y-th-10), (mid_x+tw+5, mid_y+10), (0,0,0), -1)
            cv2.putText(img_measure, text, (mid_x, mid_y), cv2.FONT_HERSHEY_SIMPLEX, 1.5, text_color, 3)

            cv2.drawMarker(overlay_measure, p1, marker_bgra, cv2.MARKER_CROSS, 40, 5)
            cv2.drawMarker(overlay_measure, p2, marker_bgra, cv2.MARKER_CROSS, 40, 5)
            cv2.line(overlay_measure, p1, p2, line_bgra, 4)
            cv2.rectangle(overlay_measure, (mid_x-5, mid_y-th-10), (mid_x+tw+5, mid_y+10), black_bgra, -1)
            cv2.putText(overlay_measure, text, (mid_x, mid_y), cv2.FONT_HERSHEY_SIMPLEX, 1.5, text_bgra, 3)

        if hasattr(garment_proc, 'debug_shapes'):
            garment_proc.debug_shapes = base_res['debug_shapes']

        try:
            img_measure = garment_proc.draw_special_markers(img_measure, base_res['valid_kps'], g_config, fixed_crotch_point)
        except TypeError:
            img_measure = garment_proc.draw_special_markers(img_measure, base_res['valid_kps'], g_config)
        
        garment_proc.validate_measurements(averaged_data, base_res['valid_kps'], g_config)

        # [SAFETY CHECKS] Stop nonsense results passing QC. Station logs showed a T-shirt and
        # upside-down, cut-off shorts measured as trousers - some still marked PASS.
        self.last_warnings = []
        self._optional_codes = getattr(config_module, 'TROUSER_OPTIONAL_CODES', [])
        if g_type in ('trousers', 'trousers_back', 'trouser_short'):
            self.last_warnings = self.check_trouser_capture(
                garment_mask, averaged_data, g_config, active_keys, code_to_name,
                base_res.get('warnings', []), pixels_per_cm)

        return proc_img_final, img_detect, base_res['edge_map'], img_measure, overlay_detect, overlay_measure, averaged_data, size, conf, suggestions