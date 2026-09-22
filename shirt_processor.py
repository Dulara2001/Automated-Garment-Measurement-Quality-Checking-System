"""
Dedicated Processor for Shirts/Tops
Handles special logic for shirt measurements dynamically based on config roles.
Features: 
- ROI size 25px for Armpits.
- Armpit Logic: Top-Most (Min Y) and Inner-Most (Left/Right).
- "Perpendicular Edge Scan" for Body Length.
- "Soft Perpendicular Adjustment" for Chest/Armpits (moves along edge to align).
"""
import cv2
import numpy as np
import math

class ShirtProcessor:
    def __init__(self):
        # --- Reference Points for Shirts ---
        # ---> UPDATED FOR 2880x2160 (4:3 Ratio) <---
        # Center of Landscape 2880 is 1440. Center of Portrait 2160 is 1080.
        self.REF_POINT_LANDSCAPE = (1900, 260) 
        self.REF_POINT_PORTRAIT = (1590, 640)
        
        # Store the last used fixed point to ensure drawing is consistent
        self.last_used_fixed_point = None
        
        # Keypoint ID for the "Right Shoulder" Anchor (Matches TOP_SHOULDER_R: 262)
        self.anchor_point_id = 262 

        # DEBUG VISUALIZATION STORAGE
        self.debug_shapes = []

    def get_fixed_reference(self, is_portrait):
        """Returns the hardcoded reference dot coordinates based on orientation."""
        return self.REF_POINT_PORTRAIT if is_portrait else self.REF_POINT_LANDSCAPE

    # def draw_alignment_guide(self, image, is_portrait):
    #     """
    #     Draws the crosshair and dot for the user to align the Right Shoulder.
    #     """
    #     h, w = image.shape[:2]
    #     cx, cy = self.get_fixed_reference(is_portrait)
        
    #     if cx < w and cy < h:
    #         cv2.circle(image, (cx, cy), 6, (0, 0, 255), -1)
    #         cv2.circle(image, (cx, cy), 25, (0, 255, 255), 2)
    #         cv2.line(image, (cx - 40, cy), (cx + 40, cy), (0, 255, 255), 1)
    #         cv2.line(image, (cx, cy - 40), (cx, cy + 40), (0, 255, 255), 1)
    #         cv2.putText(image, "ALIGN RIGHT SHOULDER", (cx - 95, cy - 40),
    #                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    #     return image

    def draw_alignment_guide(self, image, is_portrait):
        """
        Draws the crosshair, dot, and a low-opacity horizontal laser calibration line.
        """
        h, w = image.shape[:2]
        cx, cy = self.get_fixed_reference(is_portrait)
        
        if cx < w and cy < h:
            # --- NEW: Translucent Horizontal Laser Calibration Line ---
            overlay = image.copy()
            # Draw a red line across the entire width at the 'cy' (Y-axis) coordinate
            cv2.line(overlay, (0, cy), (w, cy), (0, 0, 255), 2)
            # Blend the overlay with the original image (40% opacity for the line)
            cv2.addWeighted(overlay, 0.4, image, 0.6, 0, image)
            # --------------------------------------------------------

            # Draw the Alignment Crosshair
            cv2.circle(image, (cx, cy), 6, (0, 0, 255), -1)
            cv2.circle(image, (cx, cy), 25, (0, 255, 255), 2)
            cv2.line(image, (cx - 40, cy), (cx + 40, cy), (0, 255, 255), 1)
            cv2.line(image, (cx, cy - 40), (cx, cy + 40), (0, 255, 255), 1)
            cv2.putText(image, "ALIGN RIGHT SHOULDER / LASER", (cx - 120, cy - 40),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        return image

    def adjust_points(self, raw_kps, valid_kps, fixed_point=None):
        """
        Refine T-shirt specific geometry and snap the shoulder point to the fixed reference.
        Also CLEARS the debug shapes for the new frame.
        """
        self.debug_shapes = [] # Reset debugs for new frame
        
        self.last_used_fixed_point = fixed_point
        
        if fixed_point is not None:
            # STRICT OVERRIDE: Force the anchor point to be EXACTLY the crosshair dot.
            # We removed the 'if' check so it applies even if the AI misses the shoulder.
            valid_kps[self.anchor_point_id] = fixed_point
            
        return valid_kps

    def get_point_refinement_logic(self, point_id, default_logic):
        """
        Returns the specific edge detection direction for T-shirt points.
        """
        if point_id == self.anchor_point_id:
            return 'center'
        return default_logic
    
    def refine_point(self, image_input, x, y, logic_type, search_size=20, safety_margin=20):
        """
        Detects the best edge point within a search area.
        Cleaned up version: Standard left/right/top/bottom scanning without the old complex armpit math.
        """
        h, w = image_input.shape
        x, y = int(x), int(y)
        lt = logic_type.lower()
            
        # --- 1. Define Search Box ---
        if 'left' in lt:
            x_start = max(0, x - search_size)
            x_end = min(w, x + safety_margin) 
        else: # right
            x_start = max(0, x - safety_margin)
            x_end = min(w, x + search_size)

        if 'top' in lt:
            y_start = max(0, y - search_size)
            y_end = min(h, y + safety_margin)
        elif 'hip' in lt or 'center' in lt:
            y_start = max(0, y - search_size)
            y_end = min(h, y + search_size)
        else:
            y_start = max(0, y - safety_margin)
            y_end = min(h, y + search_size)

        # Store ROI Box for Debug
        self.debug_shapes.append({
            'type': 'box',
            'coords': (x_start, y_start, x_end, y_end),
            'color': (255, 255, 0) # Cyan
        })

        box_coords = (x_start, y_start, x_end, y_end)
        roi = image_input[y_start:y_end, x_start:x_end]
        
        if roi.size == 0: 
            return (x, y), box_coords

        # --- 2. Processing ---
        blurred_roi = cv2.GaussianBlur(roi, (5, 5), 0)
        edges = cv2.Canny(blurred_roi, 20, 80) 
        roi_y, roi_x = np.where(edges > 0)
        
        if len(roi_x) == 0: 
            return (x, y), box_coords

        # --- 3. Decision Logic ---
        best_idx = 0
        
        if 'top_left' in lt: best_idx = np.argmin(roi_x + roi_y)      
        elif 'top_right' in lt: best_idx = np.argmax(roi_x - roi_y)      
        elif 'bottom_left' in lt: best_idx = np.argmin(roi_x - roi_y) 
        elif 'bottom_right' in lt: best_idx = np.argmax(roi_x + roi_y) 
        elif 'bottom_most_right' in lt: 
            max_y = np.max(roi_y) # 1. Find the absolute bottom Y value
            bottom_indices = np.where(roi_y == max_y)[0] # 2. Get all pixels sharing that exact bottom Y
            best_idx = bottom_indices[np.argmax(roi_x[bottom_indices])] # 3. Pick the one furthest right!
        elif 'left_most' in lt or 'hip_left' in lt: best_idx = np.argmin(roi_x)
        elif 'right_most' in lt or 'hip_right' in lt: best_idx = np.argmax(roi_x)
        # elif 'bottom_most_right' in lt: 
        #     max_y = np.max(roi_y) # Find the absolute bottom
        #     bottom_indices = np.where(roi_y == max_y)[0] # Get all pixels at that exact bottom Y
        #     best_idx = bottom_indices[np.argmax(roi_x[bottom_indices])]
        elif 'bottom_most' in lt: best_idx = np.argmax(roi_y)
        elif 'top_most' in lt: best_idx = np.argmin(roi_y) 
        elif 'center' in lt: return (x, y), box_coords

        final_x = x_start + roi_x[best_idx]
        final_y = y_start + roi_y[best_idx]

        return (final_x, final_y), box_coords
    
# shoulder conner finding method 
    def find_shoulder_corner(self, image_mask, rough_pt, side='right', search_radius=40):
        """
        Finds the exact shoulder corner by tracing the top edge.
        Uses a relaxed Y-penalty to allow the point to slide naturally down 
        the shoulder slope to the exact measurement hinge.
        """
        h, w = image_mask.shape
        rx, ry = int(rough_pt[0]), int(rough_pt[1])
        
        # Standard width search
        x_start = max(0, rx - search_radius)
        x_end = min(w, rx + search_radius)
        
        # Give it a bit more room to go down (+25px instead of +15px) 
        # so it can actually reach the true lower corner.
        y_start = max(0, ry - search_radius) 
        y_end = min(h, ry + 25)                        
        
        roi = image_mask[y_start:y_end, x_start:x_end]
        if roi.size == 0: return rough_pt
        
        blurred = cv2.GaussianBlur(roi, (5, 5), 0)
        edges = cv2.Canny(blurred, 20, 80)
        
        roi_y, roi_x = np.where(edges > 0)
        if len(roi_x) == 0: return rough_pt
        
        # RELAXED Y-PENALTY: Lowered from 2.0 to 0.7. 
        # This prioritizes pushing outward (X-axis) and allows the point to rest 
        # slightly lower (Y-axis) on the actual shoulder drop.
        if side == 'right':
            # Push Right, gently keep UP
            scores = roi_x - (roi_y * 1.5) 
            best_idx = np.argmax(scores)
        else: 
            # Push Left, gently keep UP
            scores = -roi_x - (roi_y * 1.5)
            best_idx = np.argmax(scores)
            
        final_x = x_start + roi_x[best_idx]
        final_y = y_start + roi_y[best_idx]
        
        # Green debug dot to visualize the detected true corner
        self.debug_shapes.append({
            'type': 'circle',
            'center': (final_x, final_y),
            'radius': 6,
            'color': (0, 255, 0) 
        })
        
        return (final_x, final_y)



    def find_circle_intersection(self, image_input, center_pt, radius_px, side='left'):
        """
        Finds the intersection of a circle with the garment edge.
        STRICT MODE: Physically erases the wrong side of the circle mask
        to ensure we ONLY get an edge on the requested side.
        """
        cx, cy = center_pt
        h, w = image_input.shape[:2] 
        
        # 1. Debug Visual (Optional)
        self.debug_shapes.append({
            'type': 'circle',
            'center': (int(cx), int(cy)),
            'radius': int(radius_px),
            'color': (0, 165, 255) # Orange
        })
        
        # 2. Draw the Circle Mask 
        # (Thickness increased to 4 to prevent 1-pixel Canny edge slippage)
        mask = np.zeros_like(image_input)
        cv2.circle(mask, (int(cx), int(cy)), int(radius_px), 255, 3)
        
        # 3. STRICT SIDE CONSTRAINT (The Fix)
        # We manually zero out pixels on the unwanted side relative to the center X.
        if side == 'left':
            # If looking Left, delete everything to the RIGHT of center
            mask[:, int(cx):] = 0 
        elif side == 'right':
            # If looking Right, delete everything to the LEFT of center
            mask[:, :int(cx)] = 0
            
        # 4. Standard Edge Detection
        blurred = cv2.GaussianBlur(image_input, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 100)
        
        # 5. Find Intersection
        intersection = cv2.bitwise_and(mask, edges)
        y_locs, x_locs = np.where(intersection > 0)
        
        if len(x_locs) > 0:
            if side == 'left':
                # Return the left-most intersection found
                idx = np.argmin(x_locs)
            else:
                # Return the right-most intersection found
                idx = np.argmax(x_locs)
            return (x_locs[idx], y_locs[idx])
        
        # Fallback: If no edge found on that side, return center
        return center_pt
    
    
    def find_edge_along_vector(self, image_input, start_pt, vector_tuple, range_forward=40, range_backward=10):
        """
        Scans along a specific vector direction to find the strongest/furthest edge.
        """
        x_c, y_c = start_pt
        vx, vy = vector_tuple
        
        # Normalize vector
        mag = math.sqrt(vx*vx + vy*vy)
        if mag == 0: return start_pt
        vx, vy = vx/mag, vy/mag
        
        best_pt = start_pt
        mask = np.zeros_like(image_input)
        
        p_start = (int(x_c - vx * range_backward), int(y_c - vy * range_backward))
        p_end = (int(x_c + vx * range_forward), int(y_c + vy * range_forward))
        
        self.debug_shapes.append({
            'type': 'line',
            'p1': p_start,
            'p2': p_end,
            'color': (255, 0, 255) # Magenta
        })
        
        cv2.line(mask, p_start, p_end, 255, 2)
        
        blurred = cv2.GaussianBlur(image_input, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 100)
        
        common = cv2.bitwise_and(mask, edges)
        y_locs, x_locs = np.where(common > 0)
        
        if len(x_locs) > 0:
            max_dist = -1
            for i in range(len(x_locs)):
                px, py = x_locs[i], y_locs[i]
                dist = (px - p_start[0])*vx + (py - p_start[1])*vy
                if dist > max_dist:
                    max_dist = dist
                    best_pt = (px, py)
            return best_pt

        return start_pt

    def scan_edge_for_perpendicular_match(self, image_input, current_pt, anchor_pt, axis_vec_start, axis_vec_end):
        """
        Scans the edge NEAR 'current_pt' (up/down) to find a point that makes
        the line (anchor_pt -> new_pt) roughly perpendicular to the Body Axis.
        """
        # 1. Determine Body Axis Vector
        ax, ay = axis_vec_start
        bx, by = axis_vec_end
        axis_dx = bx - ax
        axis_dy = by - ay
        mag_axis = math.sqrt(axis_dx**2 + axis_dy**2)
        if mag_axis == 0: return current_pt
        
        # Normalized Axis
        u_axis_x = axis_dx / mag_axis
        u_axis_y = axis_dy / mag_axis

        # 2. Extract ROI around current_pt to find edge pixels
        search_radius = 20 # Look up/down 20px
        cx, cy = int(current_pt[0]), int(current_pt[1])
        h, w = image_input.shape
        
        x_min = max(0, cx - 10) # Narrow width (stick to edge)
        x_max = min(w, cx + 10)
        y_min = max(0, cy - search_radius)
        y_max = min(h, cy + search_radius)
        
        roi = image_input[y_min:y_max, x_min:x_max]
        if roi.size == 0: return current_pt
        
        # Heavy Blur (match armpit logic)
        blurred = cv2.GaussianBlur(roi, (11, 11), 0)
        edges = cv2.Canny(blurred, 20, 80)
        y_locs, x_locs = np.where(edges > 0)
        
        if len(x_locs) == 0: return current_pt
        
        best_pt = current_pt
        min_error = float('inf')
        
        # 3. Iterate through all edge pixels in ROI
        for i in range(len(x_locs)):
            # Global coords of candidate edge pixel
            px = x_min + x_locs[i]
            py = y_min + y_locs[i]
            
            # Vector from Anchor to Candidate
            vec_x = px - anchor_pt[0]
            vec_y = py - anchor_pt[1]
            
            # Check Dot Product (Should be 0 if perpendicular)
            dot_prod = vec_x * u_axis_x + vec_y * u_axis_y
            
            # Error metric: Deviation from perpendicular (abs dot)
            # We add a small penalty for moving away from original point to prevent huge jumps
            dist_from_orig = abs(py - cy) * 0.1 
            total_error = abs(dot_prod) + dist_from_orig
            
            if total_error < min_error:
                min_error = total_error
                best_pt = (px, py)
                
        return best_pt

    def calculate_perpendicular_intersection_scan(self, image_input, p_source, p_line1, p_line2):
        """
        Projects HPS onto Hem Line, then scans perpendicular to Hem to find bottom edge.
        """
        x3, y3 = p_source
        x1, y1 = p_line1
        x2, y2 = p_line2
        
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0: return p_line1 

        t = ((x3 - x1) * dx + (y3 - y1) * dy) / (dx*dx + dy*dy)
        x_geo = x1 + t * dx
        y_geo = y1 + t * dy
        
        vec_x = x_geo - x3
        vec_y = y_geo - y3
        
        real_edge_pt = self.find_edge_along_vector(image_input, (x_geo, y_geo), (vec_x, vec_y), 50, 10)
        return real_edge_pt

    def get_best_fit_line_intersection(self, image_input, points, armpit_y_limit):
        """
        Calculates the perfect straight line through the side seam edges.
        Scans from TOP to BOTTOM along the line to find the upper edge (Point X).
        Includes a 5x5 wide net to guarantee it doesn't slip past thin Canny edges.
        """
        if len(points) < 2:
            return None

        # 1. Fit a Perfect Straight Line mathematically (x = my + c)
        ys = np.array([p[1] for p in points])
        xs = np.array([p[0] for p in points])
        
        try:
            m, c = np.polyfit(ys, xs, 1)
        except:
            return None 

        # 2. Draw the best-fit line in BLUE so you can verify it
        h_img, w_img = image_input.shape
        p_top = (int(m * 0 + c), 0)
        p_btm = (int(m * h_img + c), h_img)
        self.debug_shapes.append({
            'type': 'line',
            'p1': p_top,
            'p2': p_btm,
            'color': (255, 0, 0) # Solid Blue
        })

        # 3. Prepare Edge Map
        blurred = cv2.GaussianBlur(image_input, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 100)
        
        # 4. Find the exact intersection (Point X)
        for y in range(0, int(armpit_y_limit)):
            x = int(m * y + c)
            if 0 <= x < w_img and 0 <= y < h_img:
                # 5x5 WIDER NET: Guarantees we hit the edge!
                patch = edges[max(0, y-2):min(h_img, y+3), max(0, x-2):min(w_img, x+3)]
                if np.any(patch > 0):
                    return (x, y) 

        return None


    def calculate_upper_arm_parallel(self, image_gray, valid_kps, data, pixels_per_cm, mask=None):
        """
        1. Find right-most edges of the side seam using a TIGHT ROI.
        2. Draw straight blue line and strictly capture Point X (Upper Edge).
        3. Draw a physical Yellow line from Point X to Sleeve Top.
        4. Measure exactly the JSON size standard distance along that yellow line.
        5. Place Point Y strictly on that line (between X and Sleeve Top) using pure math.
        6. Draw parallel line strictly within the sleeve opening distance.
        """
        seam_ids = data.get('seam_points', [])
        refine_logic = data.get('seam_refine_logic', 'right_most')
        shift_in = data.get('shift_in', 1.0) 
        return_target = data.get('return', 'bottom')
        side = data.get('side', 'right')

        img_for_edge = mask if mask is not None else image_gray

        # --- 1. Get the extreme Right-Most edges of the side seam ---
        refined_seam_pts = []
        min_y = float('inf')
        for item in seam_ids:
            pid = None
            if isinstance(item, list):
                 for sub in item:
                     if sub in valid_kps: pid = sub; break
            elif isinstance(item, int): pid = item
            
            if pid and pid in valid_kps:
                pt = valid_kps[pid]
                # THE FIX: Shrink the ROI from 150 to 35 forward, 20 backward 
                # This prevents it from grabbing background noise or inner folds
                ref, _ = self.refine_point(img_for_edge, pt[0], pt[1], refine_logic, 35, 20)
                refined_seam_pts.append(ref)
                if ref[1] < min_y: min_y = ref[1]

        if len(refined_seam_pts) < 2: 
            return None

        # --- 2. Draw straight line and find Top Edge Cross Point (Point X) ---
        pt_X = self.get_best_fit_line_intersection(img_for_edge, refined_seam_pts, min_y)
        if pt_X is None: 
            return None

        if return_target == 'intersect':
            return pt_X

        # --- 3. Get the Sleeve Open Top point ---
        sleeve_top_raw = None
        sleeve_top_ids = data.get('sleeve_top_pt', [])
        if isinstance(sleeve_top_ids, list):
            for sub in sleeve_top_ids:
                if sub in valid_kps: sleeve_top_raw = valid_kps[sub]; break
        elif isinstance(sleeve_top_ids, int):
            if sleeve_top_ids in valid_kps: sleeve_top_raw = valid_kps[sleeve_top_ids]
        
        if not sleeve_top_raw: return None
        
        top_refine = data.get('top_refine', 'right_most' if side == 'right' else 'left_most')
        pt_SleeveTop, _ = self.refine_point(img_for_edge, sleeve_top_raw[0], sleeve_top_raw[1], top_refine, 50, 30)

        # --- 4. Calculate Point Y (Strictly between X and Sleeve Top) ---
        vec_x = pt_SleeveTop[0] - pt_X[0]
        vec_y = pt_SleeveTop[1] - pt_X[1]
        mag = math.sqrt(vec_x**2 + vec_y**2)
        if mag == 0: return None
        
        dir_x = vec_x / mag
        dir_y = vec_y / mag
        
        # DEBUG VISUAL: Draw the actual line from Point X to Sleeve Top (Yellow)
        self.debug_shapes.append({
            'type': 'line',
            'p1': pt_X,
            'p2': pt_SleeveTop,
            'color': (0, 255, 255) 
        })

        # Calculate exactly how far to move along the line based on the JSON file
        shift_px = shift_in * 2.54 * pixels_per_cm if pixels_per_cm > 0 else 0
        
        # Safety Check: Ensure Point Y does not overshoot the Sleeve Top
        if shift_px > mag:
            shift_px = mag
            
        # PURE MATH: Point Y is placed EXACTLY on the mathematical line. No edge scanning!
        pt_Y = (int(pt_X[0] + shift_px * dir_x), int(pt_X[1] + shift_px * dir_y))

        # DEBUG VISUAL: Draw a Green Dot to show Point Y exactly on the line
        self.debug_shapes.append({
            'type': 'circle',
            'center': pt_Y,
            'radius': 8,
            'color': (0, 255, 0) 
        })

        if return_target == 'top':
            return pt_Y

        # --- 5. Calculate Parallel Vector from the Sleeve Opening ---
        sleeve_ref_ids = data.get('sleeve_open_ref', [])
        p_ref_btm_raw = None
        
        if len(sleeve_ref_ids) >= 2:
            btm_id = sleeve_ref_ids[1]
            if isinstance(btm_id, list):
                for sub in btm_id:
                    if sub in valid_kps: p_ref_btm_raw = valid_kps[sub]; break
            elif isinstance(btm_id, int):
                if btm_id in valid_kps: p_ref_btm_raw = valid_kps[btm_id]

        if not p_ref_btm_raw: return None

        btm_refine = data.get('btm_refine', 'bottom_right' if side == 'right' else 'bottom_left')
        p_ref_btm, _ = self.refine_point(img_for_edge, p_ref_btm_raw[0], p_ref_btm_raw[1], btm_refine, 50, 30)

        par_vx = p_ref_btm[0] - pt_SleeveTop[0]
        par_vy = p_ref_btm[1] - pt_SleeveTop[1]
        par_mag = math.sqrt(par_vx**2 + par_vy**2)
        if par_mag == 0: 
            return None
        
        par_vx /= par_mag
        par_vy /= par_mag

        # --- 6. Find Point 'Z' (Constrained Parallel Line) ---
        # Draw the parallel line starting strictly from Point Y down to the sleeve
        search_distance = int(par_mag * 1.5) 
        pt_Z = self.find_edge_along_vector(img_for_edge, pt_Y, (par_vx, par_vy), search_distance, 10)

        return pt_Z


    def find_edge_along_vector(self, image_gray, start_pt, vector_tuple, range_forward=40, range_backward=10):
        """
        Scans along a specific vector direction to find the strongest/furthest edge.
        (Magenta debug lines strictly REMOVED to clean up the screen).
        """
        x_c, y_c = start_pt
        vx, vy = vector_tuple
        
        mag = math.sqrt(vx*vx + vy*vy)
        if mag == 0: return start_pt
        vx, vy = vx/mag, vy/mag
        
        best_pt = start_pt
        mask = np.zeros_like(image_gray)
        
        p_start = (int(x_c - vx * range_backward), int(y_c - vy * range_backward))
        p_end = (int(x_c + vx * range_forward), int(y_c + vy * range_forward))
        
        cv2.line(mask, p_start, p_end, 255, 2)
        
        blurred = cv2.GaussianBlur(image_gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 100)
        
        common = cv2.bitwise_and(mask, edges)
        y_locs, x_locs = np.where(common > 0)
        
        if len(x_locs) > 0:
            max_dist = -1
            for i in range(len(x_locs)):
                px, py = x_locs[i], y_locs[i]
                dist = (px - p_start[0])*vx + (py - p_start[1])*vy
                if dist > max_dist:
                    max_dist = dist
                    best_pt = (px, py)
            return best_pt

        return start_pt


    def get_final_point_location(self, p_input, valid_kps, image_gray, pixels_per_cm, logic_map, mask=None):
        
        # --- 1. STRICT ANCHOR POINT OVERRIDE ---
        if self.last_used_fixed_point is not None:
            if isinstance(p_input, int) and p_input == self.anchor_point_id:
                return self.last_used_fixed_point
            elif isinstance(p_input, list) and self.anchor_point_id in p_input:
                return self.last_used_fixed_point

        # THE FIX: Globally force the use of the solid mask to ignore internal patterns
        image_to_use = mask if mask is not None else image_gray

        # CASE A: List (Find first valid candidate)
        if isinstance(p_input, list):
            for candidate_id in p_input:
                if candidate_id in valid_kps:
                    return self.get_final_point_location(candidate_id, valid_kps, image_gray, pixels_per_cm, logic_map, mask=mask)
            return None

        # CASE B: Integer (Raw Keypoint ID)
        elif isinstance(p_input, int):
            if p_input not in valid_kps: return None
            pt = valid_kps[p_input]
            logic = self.get_point_refinement_logic(p_input, logic_map.get(p_input, 'center'))
            if logic == 'center': return pt
            
            # FIXED: Always use the mask
            final_pt, _ = self.refine_point(image_to_use, pt[0], pt[1], logic, 35, 35)
            return final_pt

        # CASE C: Dictionary (Complex Logic Configurations)
        elif isinstance(p_input, dict):
            
            # # --- 1. ARMPIT DROP LOGIC ---
            # if 'armpit_drop' in p_input:
            #     data = p_input['armpit_drop']
            #     base_id_or_list = data.get('base')
            #     drop_cm = data.get('drop_cm', 0.2)
            #     refine_logic = data.get('refine_logic', 'right_most')

            #     base_id = None
            #     if isinstance(base_id_or_list, list):
            #         for bid in base_id_or_list:
            #             if bid in valid_kps: base_id = bid; break
            #     else:
            #         if base_id_or_list in valid_kps: base_id = base_id_or_list

            #     if base_id is None: return None
            #     base_pt = valid_kps[base_id]

            #     drop_px = drop_cm * pixels_per_cm if pixels_per_cm > 0 else 10 
            #     dropped_x = int(base_pt[0])
            #     dropped_y = int(base_pt[1] + drop_px)

            #     # FIXED: Always use the mask
            #     final_pt, _ = self.refine_point(image_to_use, dropped_x, dropped_y, refine_logic, search_size=20, safety_margin=15)

            #     self.debug_shapes.append({
            #         'type': 'circle',
            #         'center': final_pt,
            #         'radius': 6,
            #         'color': (255, 100, 100) 
            #     })

            #     return final_pt

            # --- 1. ARMPIT DROP LOGIC ---
            if 'armpit_drop' in p_input:
                data = p_input['armpit_drop']
                base_id_or_list = data.get('base')
                drop_cm = data.get('drop_cm', 0.2)
                refine_logic = data.get('refine_logic', 'right_most')

                base_id = None
                if isinstance(base_id_or_list, list):
                    for bid in base_id_or_list:
                        if bid in valid_kps: base_id = bid; break
                else:
                    if base_id_or_list in valid_kps: base_id = base_id_or_list

                if base_id is None: return None
                base_pt = valid_kps[base_id]

                # STEP 1: Find the PERFECT armpit corner first (before dropping)
                perfect_corner, _ = self.refine_point(image_to_use, int(base_pt[0]), int(base_pt[1]), refine_logic, search_size=25, safety_margin=15)

                # STEP 2: Drop exactly down by drop_cm (0.2 cm / 2mm)
                drop_px = drop_cm * pixels_per_cm if pixels_per_cm > 0 else 10
                target_y = int(perfect_corner[1] + drop_px)
                target_x = int(perfect_corner[0])

                # STEP 3: Snap horizontally to the side seam edge to keep the exact Y-drop
                h, w = image_to_use.shape
                search_radius_x = 30
                x_start = max(0, target_x - search_radius_x)
                x_end = min(w, target_x + search_radius_x)

                # Narrow 5-pixel vertical slice to lock the Y-axis
                y_min = max(0, target_y - 2)
                y_max = min(h, target_y + 3)
                roi = image_to_use[y_min:y_max, x_start:x_end]

                if roi.size == 0: 
                    return (target_x, target_y)

                # Find the edge purely on the horizontal plane
                blurred_roi = cv2.GaussianBlur(roi, (3, 3), 0)
                edges = cv2.Canny(blurred_roi, 20, 80)
                roi_y, roi_x = np.where(edges > 0)

                if len(roi_x) > 0:
                    # If looking at left armpit ('top_right'), pull to the inner right edge.
                    # If looking at right armpit ('top_left'), pull to the inner left edge.
                    if 'right' in refine_logic:
                        best_idx = np.argmax(roi_x)
                    else:
                        best_idx = np.argmin(roi_x)
                    
                    final_pt = (x_start + roi_x[best_idx], target_y)
                else:
                    final_pt = (target_x, target_y)

                self.debug_shapes.append({
                    'type': 'circle',
                    'center': final_pt,
                    'radius': 6,
                    'color': (255, 100, 100) 
                })

                return final_pt

            # --- 2. UPPER ARM LOGIC ---
            if 'upper_arm_parallel' in p_input:
                return self.calculate_upper_arm_parallel(
                    image_gray, valid_kps, p_input['upper_arm_parallel'], pixels_per_cm, mask=mask
                )
            
            # --- 3. SIDE SEAM LOGIC ---
            if 'side_seam_projection' in p_input:
                data = p_input['side_seam_projection']
                seam_ids = data.get('seam_points', [])
                refine_logic = data.get('refine_logic', 'right_most')
                
                refined_seam_pts = []
                min_y = float('inf')
                for item in seam_ids:
                    pid = None
                    if isinstance(item, list):
                         for sub in item:
                             if sub in valid_kps: pid = sub; break
                    elif isinstance(item, int): pid = item
                    
                    if pid and pid in valid_kps:
                        pt = valid_kps[pid]
                        # FIXED: Always use the mask
                        ref, _ = self.refine_point(image_to_use, pt[0], pt[1], refine_logic, 30, 30)
                        refined_seam_pts.append(ref)
                        if ref[1] < min_y: min_y = ref[1]
                        
                if len(refined_seam_pts) >= 2:
                    # FIXED: Pass the mask into the line intersection helper
                    return self.get_best_fit_line_intersection(image_to_use, refined_seam_pts, min_y - 15)
                return None
            
            # --- 4. PERPENDICULAR LOGIC ---
            if 'perpendicular_projection' in p_input:
                data = p_input['perpendicular_projection']
                p_src = self.get_final_point_location(data.get('source'), valid_kps, image_gray, pixels_per_cm, logic_map, mask=mask)
                p_l1 = self.get_final_point_location(data.get('line_p1'), valid_kps, image_gray, pixels_per_cm, logic_map, mask=mask)
                p_l2 = self.get_final_point_location(data.get('line_p2'), valid_kps, image_gray, pixels_per_cm, logic_map, mask=mask)
                
                if p_src and p_l1 and p_l2:
                    # FIXED: Pass the mask into the perpendicular scanner
                    return self.calculate_perpendicular_intersection_scan(image_to_use, p_src, p_l1, p_l2)
                return None

            # --- 6. DYNAMIC LEFT SHOULDER LOGIC ---
            if 'dynamic_left_shoulder' in p_input:
                data = p_input['dynamic_left_shoulder']
                target_width_in = data.get('target_width_in', 0.0)
                
                # RECURSIVE RESOLVE: Dynamically fetch the Right Shoulder base 
                # (Can handle either the Manual UI point or the Auto-Detected point)
                base_right = data.get('base_right_shoulder', self.anchor_point_id)
                right_shoulder_pt = self.get_final_point_location(base_right, valid_kps, image_gray, pixels_per_cm, logic_map, mask=mask)
                
                if not right_shoulder_pt:
                    return None
                    
                rx, ry = right_shoulder_pt
                target_px = target_width_in * 2.54 * pixels_per_cm if pixels_per_cm > 0 else 0
                h_img, w_img = image_to_use.shape
                
                if target_px > 0:
                    expected_lx = max(0, int(rx - target_px))
                    x_start = max(0, expected_lx - 50)
                    x_end = min(w_img, expected_lx + 30)
                    y_start = max(0, int(ry) - 15)
                    y_end = min(h_img, int(ry) + 15)
                else:
                    x_start = 0
                    x_end = max(0, int(rx) - 50) 
                    y_start = max(0, int(ry) - 60)
                    y_end = min(h_img, int(ry) + 40)
                    
                roi = image_to_use[y_start:y_end, x_start:x_end]
                if roi.size == 0: return (rx, ry)
                
                self.debug_shapes.append({
                    'type': 'box',
                    'coords': (x_start, y_start, x_end, y_end),
                    'color': (0, 165, 255) 
                })
                
                blurred = cv2.GaussianBlur(roi, (5, 5), 0)
                edges = cv2.Canny(blurred, 30, 100)
                roi_y, roi_x = np.where(edges > 0)
                
                if len(roi_x) == 0:
                    return (max(0, rx - target_px), ry) if target_px > 0 else (rx, ry)
                    
                best_idx = np.argmin(roi_x)
                final_x = x_start + roi_x[best_idx]
                final_y = y_start + roi_y[best_idx]
                
                return (final_x, final_y)

            # --- 7. AUTOMATED SHOULDER CORNER LOGIC ---
            if 'shoulder_corner' in p_input:
                data = p_input['shoulder_corner']
                base_id_or_list = data.get('base')
                side = data.get('side', 'right')

                base_id = None
                if isinstance(base_id_or_list, list):
                    for bid in base_id_or_list:
                        if bid in valid_kps: base_id = bid; break
                else:
                    if base_id_or_list in valid_kps: base_id = base_id_or_list

                if base_id is None: return None
                
                raw_pt = valid_kps[base_id]
                final_pt = self.find_shoulder_corner(image_to_use, raw_pt, side=side)
                
                # SAVE THE AUTO POINT TO MEMORY FOR THE SLEEVE LENGTH
                if side == 'right':
                    self.latest_right_shoulder = final_pt
                    
                return final_pt

            # --- 8. MANUAL SHOULDER LOGIC ---
            if 'manual_shoulder' in p_input:
                # Always prioritize the UI reference dot if it is placed
                if self.last_used_fixed_point is not None:
                    final_pt = self.last_used_fixed_point
                else:
                    base_id = p_input['manual_shoulder'].get('base', self.anchor_point_id)
                    final_pt = valid_kps.get(base_id, (0, 0))
                    
                # SAVE THE MANUAL POINT TO MEMORY FOR THE SLEEVE LENGTH
                self.latest_right_shoulder = final_pt
                return final_pt
                
            # --- 9. SMART LATEST SHOULDER (FOR SLEEVE LENGTH F) ---
            if 'use_latest_shoulder' in p_input:
                # Magically returns whichever point (Manual or Auto) was calculated last!
                if hasattr(self, 'latest_right_shoulder') and self.latest_right_shoulder is not None:
                    return self.latest_right_shoulder
                else:
                    # Absolute fallback just in case F runs completely alone
                    return self.last_used_fixed_point if self.last_used_fixed_point else valid_kps.get(self.anchor_point_id)
            

            # --- 5. STANDARD REFINEMENT LOGIC ---
            base_id_or_list = p_input.get('base')
            base_id = None
            if isinstance(base_id_or_list, list):
                for bid in base_id_or_list:
                    if bid in valid_kps: base_id = bid; break
            else:
                if base_id_or_list in valid_kps: base_id = base_id_or_list

            if base_id is None: return None
            base_pt = valid_kps[base_id]
            
            scan_logic = p_input.get('find_edge', None)
            if not scan_logic:
                scan_logic = self.get_point_refinement_logic(base_id, logic_map.get(base_id, 'center'))
            
            # FIXED: Always use the mask
            refined_pt, _ = self.refine_point(image_to_use, base_pt[0], base_pt[1], scan_logic, 50, 20)
            
            # Optional: Circular Intersection
            if 'circular_intersect' in p_input and pixels_per_cm > 0:
                circ_data = p_input['circular_intersect']
                r_cm = circ_data.get('radius_cm', 1.0)
                side = circ_data.get('side', 'left')
                r_px = r_cm * pixels_per_cm
                # FIXED: Pass the mask into the circle intersection helper
                refined_pt = self.find_circle_intersection(image_to_use, refined_pt, r_px, side)
            
            # Optional: Manual Coordinate Shift
            shift_val = p_input.get('shift_cm', 0.0)
            shift_dir = p_input.get('direction', '')
            if shift_val != 0 and pixels_per_cm > 0:
                shift_px = shift_val * pixels_per_cm
                rx, ry = refined_pt
                if shift_dir == 'left': rx -= shift_px
                elif shift_dir == 'right': rx += shift_px
                elif shift_dir == 'up': ry -= shift_px
                elif shift_dir == 'down': ry += shift_px
                refined_pt = (rx, ry)

            return refined_pt

        return None


    def _get_point_id(self, role, config, valid_kps):
        candidates = config.get('point_candidates', {}).get(role, [])
        if isinstance(candidates, int): candidates = [candidates]
        for pid in candidates:
            if pid in valid_kps:
                return pid
        return None

    def validate_measurements(self, measurements, valid_kps, config):
        issues = []
        shoulder_left = self._get_point_id('shoulder_left', config, valid_kps)
        hem_bottom = self._get_point_id('hem_left', config, valid_kps)
        if shoulder_left is not None and hem_bottom is not None:
            if valid_kps[shoulder_left][1] > valid_kps[hem_bottom][1]:
                issues.append("Shoulders detected below hem - check orientation")
        return issues
    
    # def draw_special_markers(self, image, valid_kps, config, fixed_point=None):

    #     for shape in self.debug_shapes:
    #         if shape['type'] == 'box':
    #             continue
                
    #         elif shape['type'] == 'circle':
    #             # Allow the Green 'Y' Point Dot to be drawn
    #             if shape.get('color') == (0, 255, 0):
    #                 cv2.circle(image, shape['center'], shape['radius'], shape['color'], -1)
    #             else:
    #                 continue
            
    #         elif shape['type'] == 'line':
    #             # Filter out the red and orange debug lines
    #             if shape['color'] == (0, 0, 255) or shape['color'] == (0, 165, 255):
    #                 continue
                
    #             # Draw the Blue and Yellow Vector lines
    #             p1 = shape['p1']
    #             p2 = shape['p2']
    #             cv2.line(image, p1, p2, shape['color'], 2)

    #     # Keep the Reference Target (the red/yellow dot) for Neck Alignment
    #     pt_to_draw = fixed_point if fixed_point is not None else self.last_used_fixed_point
    #     if pt_to_draw:
    #         cx, cy = pt_to_draw
    #         h, w = image.shape[:2]
    #         if 0 <= cx < w and 0 <= cy < h:
    #             cv2.circle(image, (cx, cy), 6, (0, 0, 255), -1)
    #             cv2.circle(image, (cx, cy), 25, (0, 255, 255), 2)
    #             cv2.putText(image, "REF", (cx - 20, cy - 35), 
    #                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                           
    #     return image

    def draw_special_markers(self, image, valid_kps, config, fixed_point=None):

        for shape in self.debug_shapes:
            if shape['type'] == 'box':
                continue
                
            elif shape['type'] == 'circle':
                # Allow the Green 'Y' Point Dot to be drawn
                if shape.get('color') == (0, 255, 0):
                    cv2.circle(image, shape['center'], shape['radius'], shape['color'], -1)
                else:
                    continue
            
            elif shape['type'] == 'line':
                # Filter out the red and orange debug lines
                if shape['color'] == (0, 0, 255) or shape['color'] == (0, 165, 255):
                    continue
                
                # Draw the Blue and Yellow Vector lines
                p1 = shape['p1']
                p2 = shape['p2']
                cv2.line(image, p1, p2, shape['color'], 2)
                           
        return image