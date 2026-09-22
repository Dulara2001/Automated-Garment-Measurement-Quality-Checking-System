import cv2
import numpy as np
import math

class TrouserProcessor:
    def __init__(self):
        # Crotch points (Left and Right) - Matches your Config IDs
        self.crotch_left = 234
        self.crotch_right = 258
        
        # 2880x2160
        # Fixed Reference Points (Standardized for UI alignment)
        self.CROTCH_POINT_LANDSCAPE = (1400, 600) 
        self.CROTCH_POINT_PORTRAIT = (1050, 800)
        
        # Store the last used fixed point to ensure drawing is consistent
        self.last_used_fixed_point = None
        
        # NEW: Initialize debug shapes array for the engine to consume
        self.debug_shapes = []

        # Set by calculate_crotch_drop() when a measurement had to fall back to an
        # estimated inside edge, so the caller can surface a warning.
        self.last_crotch_drop_note = None

        # --- PER-FRAME STATE (reset in adjust_points) ---
        self.ai_crotch_point = None      # crotch from the AI model, before any override
        self.ai_crotch_candidates = []   # raw AI crotch keypoints (234, 258)
        self.crotch_point = None         # the crotch actually used for measuring
        self.color_frame = None          # BGR frame, set by the engine (needed for thread colour)
        self.warnings = []               # list of {'level': 'info'|'retake', 'message': str}
        self._cache = {}                 # per-frame results shared between p1/p2 resolvers

    def get_fixed_reference(self, is_portrait):
        """Returns the hardcoded reference dot coordinates based on orientation."""
        return self.CROTCH_POINT_PORTRAIT if is_portrait else self.CROTCH_POINT_LANDSCAPE

    def draw_alignment_guide(self, image, is_portrait):
        """
        Draws the crosshair and dot for the user to align the garment.
        """
        h, w = image.shape[:2]
        cx, cy = self.get_fixed_reference(is_portrait)
        
        # Only draw if within bounds
        if cx < w and cy < h:
            # Draw visual guides
            cv2.circle(image, (cx, cy), 6, (0, 0, 255), -1)
            cv2.circle(image, (cx, cy), 25, (0, 255, 255), 2)
            cv2.line(image, (cx - 40, cy), (cx + 40, cy), (0, 255, 255), 1)
            cv2.line(image, (cx, cy - 40), (cx, cy + 40), (0, 255, 255), 1)
            cv2.putText(image, "ALIGN CROTCH", (cx - 70, cy - 40),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        return image
        
    def adjust_points(self, keypoints, valid_kps, fixed_crotch_point=None):
        """
        Forces crotch points to a specific location if provided.
        This sets the STARTING position for the measurements.
        """
        # NEW: Reset shapes per frame
        self.debug_shapes = []
        self._cache = {}
        self.warnings = []
        self.crotch_point = None

        # Remember where the AI put the crotch BEFORE the red dot overrides it,
        # so refine_crotch() can cross-check the operator's alignment.
        self.ai_crotch_candidates = [tuple(map(int, valid_kps[k]))
                                     for k in (self.crotch_left, self.crotch_right) if k in valid_kps]
        self.ai_crotch_point = None
        if self.crotch_left in valid_kps and self.crotch_right in valid_kps:
            (lx, ly), (rx, ry) = valid_kps[self.crotch_left], valid_kps[self.crotch_right]
            self.ai_crotch_point = (int((lx + rx) / 2), int(max(ly, ry)))
        elif self.crotch_left in valid_kps:
            self.ai_crotch_point = tuple(map(int, valid_kps[self.crotch_left]))

        # Reset or Set the fixed point for this processing cycle
        self.last_used_fixed_point = fixed_crotch_point
        
        if fixed_crotch_point is not None:
            # 1. FORCE override to the red dot (Fixed Reference Point)
            fx, fy = fixed_crotch_point
            
            # Update the keypoints to match the fixed reference
            valid_kps[self.crotch_left] = (fx, fy)
            valid_kps[self.crotch_right] = (fx, fy)
            
        elif self.crotch_left in valid_kps and self.crotch_right in valid_kps:
            # Default behavior if no fixed point: flatten to lower detected point
            pt_left = valid_kps[self.crotch_left]
            pt_right = valid_kps[self.crotch_right]
            max_y = max(pt_left[1], pt_right[1])
            valid_kps[self.crotch_left] = (pt_left[0], max_y)
            valid_kps[self.crotch_right] = (pt_right[0], max_y)
        
        return valid_kps
    
    def get_point_refinement_logic(self, point_id, default_logic):
        """
        Determines if we should search for edges or stay put.
        """
        # [CROTCH LOCK] Force these points to 'center'.
        # 'center' tells the engine: "Do NOT refine/move this point."
        if point_id == self.crotch_left or point_id == self.crotch_right:
            return 'center'
            
        return default_logic
    
    def refine_point(self, image_gray, x, y, logic_type, search_size=45, safety_margin=25):
        """
        Detects the best edge point for Trousers within a search area.
        OPTIMIZED: Uses Numpy Vectorization for speed.
        """
        h, w = image_gray.shape
        x, y = int(x), int(y)
        lt = logic_type.lower()
        
        # Define Search Box
        if 'left' in lt:
            x_start = max(0, x - search_size)
            x_end = min(w, x + safety_margin) 
        else:
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

        box_coords = (x_start, y_start, x_end, y_end)
        roi = image_gray[y_start:y_end, x_start:x_end]
        if roi.size == 0: return (x, y), box_coords

        # Fast Gaussian Blur (sufficient for edge detection on trousers)
        blurred_roi = cv2.GaussianBlur(roi, (5, 5), 0)
        edges = cv2.Canny(blurred_roi, 30, 100) 
        
        # Get edge coordinates
        roi_y, roi_x = np.where(edges > 0)
        
        if len(roi_x) == 0: return (x, y), box_coords

        # --- OPTIMIZED: Vectorized Decision Logic ---
        best_idx = 0
        
        if 'top_left' in lt: best_idx = np.argmin(roi_x + roi_y)      
        elif 'top_right' in lt: best_idx = np.argmax(roi_x - roi_y)      
        elif 'bottom_left' in lt: best_idx = np.argmin(roi_x - roi_y)      
        elif 'bottom_right' in lt: best_idx = np.argmax(roi_x + roi_y)
        elif 'left_most' in lt or 'hip_left' in lt: best_idx = np.argmin(roi_x)
        elif 'right_most' in lt or 'hip_right' in lt: best_idx = np.argmax(roi_x)
        elif 'bottom_most' in lt: best_idx = np.argmax(roi_y)
        elif 'top_most' in lt: best_idx = np.argmin(roi_y) 
        elif 'center' in lt: return (x, y), box_coords

        final_x = x_start + roi_x[best_idx]
        final_y = y_start + roi_y[best_idx]
        return (final_x, final_y), box_coords

    # =====================================================================================
    # PANT POM ENGINE (customer spec "3889 and pant Spec")
    # All helpers below work on the solid U2-Net mask supplied by the engine.
    # =====================================================================================

    def _px_per_cm(self, pixels_per_cm):
        return pixels_per_cm if pixels_per_cm and pixels_per_cm > 0 else 12.0

    def _warn(self, message, level='info'):
        if not any(w['message'] == message for w in self.warnings):
            self.warnings.append({'level': level, 'message': message})

    def set_color_frame(self, frame):
        """Called by the engine each frame; fly-stitch detection needs colour."""
        self.color_frame = frame

    def _inside(self, mask, x, y):
        h, w = mask.shape[:2]
        xi, yi = int(round(x)), int(round(y))
        return 0 <= xi < w and 0 <= yi < h and mask[yi, xi] > 127

    def _march_to_edge(self, mask, start, direction, max_px):
        """Walk from `start` along `direction` while inside the garment; return the last inside point."""
        dx, dy = direction
        norm = math.hypot(dx, dy) or 1.0
        dx, dy = dx / norm, dy / norm
        x, y = float(start[0]), float(start[1])
        last = None
        for _ in range(int(max_px)):
            if self._inside(mask, x, y):
                last = (int(round(x)), int(round(y)))
            elif last is not None:
                break
            x += dx
            y += dy
        return last

    def _find_leg_gap_apex(self, mask, pixels_per_cm):
        """
        Top of the gap between the legs, from the silhouette (deepest central dent).
        Returns (x, y) or None if the shape has no leg gap (e.g. not trousers).
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            return None
        outline = max(contours, key=cv2.contourArea)
        hull = cv2.convexHull(outline, returnPoints=False)
        try:
            defects = cv2.convexityDefects(outline, hull)
        except cv2.error:
            return None
        if defects is None:
            return None

        bx, by, bw, bh = cv2.boundingRect(outline)
        min_depth = 2.5 * self._px_per_cm(pixels_per_cm)          # a real leg gap is > 2.5 cm deep
        best = None
        for s, e, f, depth in defects[:, 0]:
            px, py = outline[f][0]
            depth_px = depth / 256.0
            central = bx + 0.25 * bw < px < bx + 0.75 * bw
            upper = by + 0.15 * bh < py < by + 0.80 * bh
            if central and upper and depth_px > min_depth:
                if best is None or depth_px > best[0]:
                    best = (depth_px, (int(px), int(py)))
        return best[1] if best else None

    def refine_crotch(self, valid_kps, mask, pixels_per_cm):
        """
        [AUTO CROTCH CHECK] Make sure the crotch used for measuring is on the real crotch seam.

        Lessons from real station photos:
          - The operator's red dot is usually right, but was once found sitting on a pocket.
          - The top of the gap between the legs is NOT the crotch seam: the fabric overlaps above it,
            so the gap starts 0.5-2 in below the seam, even when the legs are apart.
          - The AI's two crotch points (234, 258) are near the seam, but one can be wildly wrong.

        So the leg gap is used to decide WHERE the seam can be, then the seam point is taken from:
          1. the red dot, if it lies in that zone (the company's intended workflow)
          2. otherwise the AI crotch point in that zone closest to the gap
          3. otherwise the top of the gap, with a warning
        Enabled by TROUSER_CROTCH_MODE = "auto" in garment_config.py.
        """
        if mask is None:
            return valid_kps
        dot = self.last_used_fixed_point
        apex = self._find_leg_gap_apex(mask, pixels_per_cm)
        ai = list(self.ai_crotch_candidates or [])

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            return valid_kps
        _, _, _, bh = cv2.boundingRect(max(contours, key=cv2.contourArea))

        def in_zone(pt):
            # The seam is a little ABOVE the top of the leg gap, and roughly above it.
            return (pt is not None and apex is not None
                    and abs(pt[0] - apex[0]) <= 0.06 * bh
                    and apex[1] - 0.10 * bh <= pt[1] <= apex[1] + 0.02 * bh)

        crotch, how = None, ""
        if apex is not None:
            if in_zone(dot):
                crotch, how = dot, "red dot"
            else:
                plausible = [p for p in ai if in_zone(p)]
                if plausible:
                    crotch = max(plausible, key=lambda p: p[1])      # closest to the gap
                    how = "AI point"
                    if dot is not None:
                        off_in = math.hypot(dot[0] - crotch[0], dot[1] - crotch[1]) / (self._px_per_cm(pixels_per_cm) * 2.54)
                        self._warn(f"Garment was not lined up with the red dot (about {off_in:.1f} in off). "
                                   f"The crotch seam was found automatically.")
                else:
                    crotch, how = apex, "top of leg gap"
                    self._warn("Crotch seam not found; used the top of the leg gap, which sits slightly low "
                               "(inseam may read short, rise long). Check the garment is laid flat.")
        else:
            if dot is not None:
                crotch, how = dot, "red dot (no leg gap visible)"
                self._warn("Gap between the legs not visible; crotch taken from the red dot.")
            elif len(ai) == 2 and math.hypot(ai[0][0] - ai[1][0], ai[0][1] - ai[1][1]) <= 0.05 * bh:
                crotch = (int((ai[0][0] + ai[1][0]) / 2), int((ai[0][1] + ai[1][1]) / 2))
                how = "AI point (no leg gap visible)"
                self._warn("Gap between the legs not visible; crotch estimated from the AI points.")
            else:
                self._warn("Crotch could not be found. Lay the legs slightly apart and retake.", level='retake')
                return valid_kps

        self.crotch_point = (int(crotch[0]), int(crotch[1]))
        valid_kps[self.crotch_left] = self.crotch_point
        valid_kps[self.crotch_right] = self.crotch_point
        self.debug_shapes.append({'type': 'circle', 'center': self.crotch_point, 'radius': 10,
                                  'color': (255, 0, 255), 'label': f"crotch ({how})"})
        return valid_kps

    def _crotch(self, valid_kps):
        if self.crotch_point is not None:
            return self.crotch_point
        if self.last_used_fixed_point is not None:
            return tuple(map(int, self.last_used_fixed_point))
        if self.crotch_left in valid_kps:
            return tuple(map(int, valid_kps[self.crotch_left]))
        return None

    def waist_top_center(self, valid_kps, image_gray, pixels_per_cm, logic_map, mask, data):
        """
        [CUSTOMER POMs K-01 FRONT RISE, K-05 BACK RISE] Top edge of the waistband at the centre.
        Midpoint of the two refined waist corners, snapped up to the top edge of the silhouette.
        """
        key = 'waist_top_center'
        if key in self._cache:
            return self._cache[key]
        left = self.get_final_point_location(data.get('left'), valid_kps, image_gray, pixels_per_cm, logic_map, mask=mask)
        right = self.get_final_point_location(data.get('right'), valid_kps, image_gray, pixels_per_cm, logic_map, mask=mask)
        if left is None or right is None:
            self._cache[key] = None
            return None
        mx = int((left[0] + right[0]) / 2)
        my = int((left[1] + right[1]) / 2)
        result = (mx, my)
        if mask is not None:
            span = int(2.5 * self._px_per_cm(pixels_per_cm))
            h = mask.shape[0]
            column = mask[max(0, my - span):min(h, my + span), mx] if 0 <= mx < mask.shape[1] else []
            rows = np.where(np.asarray(column) > 127)[0]
            if len(rows):
                result = (mx, max(0, my - span) + int(rows[0]))
        self._cache[key] = result
        return result

    def hip_3point(self, valid_kps, image_gray, pixels_per_cm, logic_map, mask, data):
        """
        [CUSTOMER POM I-26 HIP - 3 POINT METHOD]
        "Measure across the width of the garment maintaining a 90 degree angle to the rise seam,
         at the placement specified."
          1. rise seam = waistband top centre -> crotch
          2. go down the rise seam to the hip placement
          3. measure straight across at 90 degrees to the rise seam, edge to edge

        PLACEMENT IS NOT CONFIRMED by the customer. Set HIP_DROP_CM (exact distance below the
        waistband) or HIP_RISE_FRACTION (share of the rise) in garment_config.py.
        """
        side = data.get('side', 'left')
        key = ('hip', data.get('drop_cm'), data.get('rise_fraction'))
        if key not in self._cache:
            self._cache[key] = None
            top = self.waist_top_center(valid_kps, image_gray, pixels_per_cm, logic_map, mask,
                                        {'left': data.get('waist_left'), 'right': data.get('waist_right')})
            crotch = self._crotch(valid_kps)
            if top is not None and crotch is not None and mask is not None:
                rx, ry = crotch[0] - top[0], crotch[1] - top[1]
                rise_len = math.hypot(rx, ry)
                if rise_len > 1:
                    ux, uy = rx / rise_len, ry / rise_len
                    if data.get('drop_cm'):
                        dist = min(data['drop_cm'] * self._px_per_cm(pixels_per_cm), rise_len * 0.95)
                    else:
                        dist = rise_len * float(data.get('rise_fraction', 0.75))
                    hx, hy = top[0] + ux * dist, top[1] + uy * dist
                    nx, ny = -uy, ux                                    # 90 degrees to the rise seam
                    max_px = mask.shape[1]
                    a = self._march_to_edge(mask, (hx, hy), (nx, ny), max_px)
                    b = self._march_to_edge(mask, (hx, hy), (-nx, -ny), max_px)
                    if a and b:
                        self._cache[key] = (a, b) if a[0] < b[0] else (b, a)
        pair = self._cache[key]
        if pair is None:
            return None
        return pair[0] if side == 'left' else pair[1]

    def thigh_perpendicular(self, mask, valid_kps, data, pixels_per_cm):
        """
        [CUSTOMER POM L-02 THIGH] "Measure straight across the width, 2.5cm/1" below crotch seam.
        The line is to be at a 90 degree angle to the inside leg at the crotch."

          1. find the inside seam line of the leg: fit the inside edge of the leg where it is clearly
             visible (below the leg gap, where the edge is straight - not the flared top of the gap)
          2. extend that line up to the crotch and go 1 inch down it
          3. measure across the leg at 90 degrees, from the seam line to the outside edge

        Near the crotch the legs usually overlap in the photo, so the inside edge is hidden there.
        The measurement then starts ON the seam line (where the seam really is) instead of wandering
        into the other leg.

        Returns (inner, outer) or None when the seam line can't be traced.
        """
        leg = data.get('leg', 'left')
        drop_cm = data.get('drop_cm', 2.54)
        key = ('thigh', leg, drop_cm)
        if key in self._cache:
            return self._cache[key]
        self._cache[key] = None
        crotch = self._crotch(valid_kps)
        if crotch is None or mask is None:
            return None

        ppcm = self._px_per_cm(pixels_per_cm)
        cx, cy = crotch
        apex = self._find_leg_gap_apex(mask, pixels_per_cm)
        gap_top = apex[1] if apex is not None else cy

        # 1. Inside edge of the leg, sampled where it is straight (well below the top of the gap)
        ys, xs = [], []
        step = max(1, int(0.3 * ppcm))
        for y in range(int(gap_top + 3 * ppcm), int(gap_top + 25 * ppcm), step):
            runs = self._row_runs(mask, y)
            if len(runs) < 2:
                continue
            if leg == 'left':
                side = [r for r in runs if r[1] <= cx + 3 * ppcm]
                if side:
                    ys.append(y); xs.append(side[-1][1])
            else:
                side = [r for r in runs if r[0] >= cx - 3 * ppcm]
                if side:
                    ys.append(y); xs.append(side[0][0])
        if len(ys) < 8:
            return None

        a, b = np.polyfit(np.array(ys, float), np.array(xs, float), 1)     # seam line: x = a*y + b
        # Anchor the seam line at the crotch (same direction, passing through the crotch point)
        b = cx - a * cy
        dnorm = math.hypot(a, 1.0)
        dx, dy = a / dnorm, 1.0 / dnorm                                     # down the inside leg

        # 2. One inch down the seam line from the crotch
        px, py = cx + drop_cm * ppcm * dx, cy + drop_cm * ppcm * dy

        # 3. 90 degrees to the seam, pointing out of this leg
        nx, ny = -dy, dx
        if (leg == 'left' and nx > 0) or (leg == 'right' and nx < 0):
            nx, ny = -nx, -ny

        # Inner end: the seam line itself, unless the real inside edge is visible just outside it
        inner = (int(round(px)), int(round(py)))
        if not self._inside(mask, px, py):
            # the gap is already open here: step outward onto the fabric edge
            found = None
            for t in range(1, int(3 * ppcm)):
                if self._inside(mask, px + nx * t, py + ny * t):
                    found = (int(round(px + nx * t)), int(round(py + ny * t)))
                    break
            if found is None:
                return None
            inner = found

        outer = self._march_to_edge(mask, inner, (nx, ny), mask.shape[1])
        if outer is None or math.hypot(outer[0] - inner[0], outer[1] - inner[1]) < 2 * ppcm:
            return None
        self._cache[key] = (inner, outer)
        return self._cache[key]

    def fly_j_stitch(self, valid_kps, image_gray, pixels_per_cm, logic_map, mask, data):
        """
        [CUSTOMER POM N-01 FLY LENGTH] "Measure the length of the fly straight down from the fly
        top seam to the bottom fly along rise seam" (to the bottom of the 'J' stitch).

        EXPERIMENTAL. Stitch thread is lighter than the fabric around it, so it shows up as thin
        bright lines. The fly is the long vertical stitch line beside the centre front: its top is the
        waistband seam, and it curves in to meet the centre seam at the bottom of the 'J'.
        Returns None - so the measurement is skipped, not guessed - when no clear fly stitch is
        found (low-resolution photo, tonal thread on very dark fabric, blur).
        """
        key = 'fly'
        if key not in self._cache:
            self._cache[key] = None
            self._cache[key] = self._detect_fly(valid_kps, image_gray, pixels_per_cm, logic_map, mask)
            if self._cache[key] is None:
                self._warn("Fly length not measured: no clear fly stitching found.")
        pair = self._cache[key]
        if pair is None:
            return None
        return pair[0] if data.get('return', 'top') == 'top' else pair[1]

    def _detect_fly(self, valid_kps, image_gray, pixels_per_cm, logic_map, mask):
        frame = self.color_frame
        if frame is None or mask is None:
            return None
        top = self.waist_top_center(valid_kps, image_gray, pixels_per_cm, logic_map, mask,
                                    {'left': 284, 'right': 290})
        crotch = self._crotch(valid_kps)
        if top is None or crotch is None or crotch[1] <= top[1]:
            return None

        ppcm = self._px_per_cm(pixels_per_cm)
        h, w = frame.shape[:2]
        cx = int((top[0] + crotch[0]) / 2)
        y0, y1 = int(top[1] + 1.5 * ppcm), int(crotch[1] - 0.5 * ppcm)
        half = int(6 * ppcm)
        x0, x1 = max(0, cx - half), min(w, cx + half)
        if y1 - y0 < 5 * ppcm or x1 - x0 < 4 * ppcm:
            return None
        if (x1 - x0) < 150:                      # too few pixels to see stitching at all
            return None

        # Thin bright lines (thread) in the centre-front area
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        k = max(3, int(0.5 * ppcm)) | 1
        tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        lines = (tophat > max(float(np.percentile(tophat, 94)), 8.0)).astype(np.uint8)
        lines[mask[y0:y1, x0:x1] < 128] = 0
        joined = cv2.dilate(lines, np.ones((max(3, int(0.6 * ppcm)), 1), np.uint8))   # join dashes
        rh, rw = joined.shape
        ccx = cx - x0

        # 1. The fly column: most stitching in the upper part, beside (not on) the centre seam
        upper = joined[: int(rh * 0.55)]
        col_score = upper.sum(axis=0).astype(float)
        offsets = np.abs(np.arange(rw) - ccx)
        col_score[(offsets < 1.2 * ppcm) | (offsets > 5.5 * ppcm)] = 0
        col_score = np.convolve(col_score, np.ones(5) / 5, mode="same")
        line_x = int(np.argmax(col_score))
        if col_score[line_x] / max(1, upper.shape[0]) < 0.35:
            return None

        # 2. Waistband seam: the lowest wide horizontal stitch line near the top
        row_frac = lines.sum(axis=1) / float(rw)
        wide = [y for y in range(int(0.35 * rh)) if row_frac[y] > 0.22]
        waist_seam = max(wide) if wide else 0

        # 3. Longest vertical run of stitching in that column below the waistband (gaps <= 1 cm)
        win = max(2, int(0.3 * ppcm))
        col = joined[:, max(0, line_x - win):min(rw, line_x + win + 1)].max(axis=1) > 0
        col[:waist_seam + 1] = False
        max_gap = int(1.0 * ppcm)
        best, run_start, last_on, gap = (0, 0, 0), None, None, 0
        for y, on in enumerate(col):
            if on:
                if run_start is None:
                    run_start = y
                last_on, gap = y, 0
            elif run_start is not None:
                gap += 1
                if gap > max_gap:
                    if last_on - run_start > best[0]:
                        best = (last_on - run_start, run_start, last_on)
                    run_start, gap = None, 0
        if run_start is not None and last_on - run_start > best[0]:
            best = (last_on - run_start, run_start, last_on)
        length, start_y, run_end = best
        if length < 3 * ppcm:
            return None

        # 4. Follow the curve in from the end of the straight part to the centre seam
        side = 1 if line_x > ccx else -1
        x_prev, last_y = line_x, run_end
        inner_limit = ccx + side * int(0.4 * ppcm)
        for y in range(run_end, min(rh, run_end + int(6 * ppcm))):
            if side > 0:
                seg = joined[y, inner_limit:min(rw, x_prev + win + 1)]
                xs = np.where(seg > 0)[0] + inner_limit
            else:
                lo = max(0, x_prev - win)
                seg = joined[y, lo:inner_limit + 1]
                xs = np.where(seg > 0)[0] + lo
            if len(xs) == 0:
                if y - last_y > int(0.8 * ppcm):
                    break
                continue
            x_prev = int(xs.min()) if side > 0 else int(xs.max())
            last_y = y
            if abs(x_prev - ccx) <= int(0.6 * ppcm):
                break

        top_y = waist_seam if wide else start_y
        bottom = (x0 + int(x_prev), y0 + int(last_y))
        top_pt = (bottom[0], y0 + int(top_y))                          # measured straight down
        fly_cm = (bottom[1] - top_pt[1]) / ppcm
        if not (4.0 <= fly_cm <= 25.0):                                  # not a plausible fly
            return None
        self.debug_shapes.append({'type': 'line', 'p1': top_pt, 'p2': bottom, 'color': (0, 200, 255)})
        return (top_pt, bottom)

    def _row_runs(self, img, y, min_len=4):
        """
        Returns the horizontal runs of garment pixels on one row -> [(x_start, x_end), ...].
        Above the crotch there is ONE run (the body); below it there are TWO (the legs).
        Expects a solid mask. Returns [] if the row is empty or out of bounds.
        """
        if img is None or y < 0 or y >= img.shape[0]:
            return []
        xs = np.where(img[y] > 127)[0]
        if len(xs) == 0:
            return []
        splits = np.where(np.diff(xs) > 1)[0]
        groups = np.split(xs, splits + 1)
        return [(int(g[0]), int(g[-1])) for g in groups if len(g) >= min_len]

    def _is_binary_mask(self, img):
        """True if the image is a solid mask (only black and white)."""
        if img is None or img.ndim != 2:
            return False
        return bool(np.isin(img[::8, ::8], (0, 255)).all())

    def calculate_crotch_drop(self, image_to_use, valid_kps, data, pixels_per_cm):
        """
        [CUSTOMER POM: L-02 THIGH, and any 'measure across the leg N cm below crotch']

        Mirrors the shirt processor's 'armpit_drop' idea, but for trousers:
          STEP 1: start from the crotch point
          STEP 2: drop straight down by drop_cm
          STEP 3: snap sideways to the leg edge, keeping the exact Y

        data keys:
          base      keypoint id (or list of candidate ids) for the crotch
          drop_cm   how far below the crotch to measure (2.54 = 1 inch)
          leg       'left' | 'right'  - which leg to measure
          edge      'outer' | 'inner' - which side of that leg to return

        NOTE: v1 measures on a HORIZONTAL line. The customer's rule for L-02 is 90 degrees
        to the inside leg seam. On straight-leg jeans lying flat the inside seam is close to
        vertical so the difference is small, but this should be upgraded to a perpendicular
        scan (see shirt_processor.get_best_fit_line_intersection for the pattern).
        """
        base_id_or_list = data.get('base')
        drop_cm = data.get('drop_cm', 2.54)
        leg = data.get('leg', 'left')
        edge = data.get('edge', 'outer')

        # PREFERRED: the customer's exact rule, 90 degrees to the inside leg.
        if data.get('perpendicular', True) and self._is_binary_mask(image_to_use):
            pair = self.thigh_perpendicular(image_to_use, valid_kps, data, pixels_per_cm)
            if pair is not None:
                return pair[0] if edge == 'inner' else pair[1]
            self._warn("Thigh measured straight across: the inside edge of the leg was hidden "
                       "(legs touching). Lay the legs slightly apart for the exact 90-degree line.")

        # Resolve the crotch point. Prefer the auto-found crotch, then the operator's red dot.
        base_pt = None
        if self.crotch_point is not None:
            base_pt = self.crotch_point
        elif self.last_used_fixed_point is not None:
            base_pt = self.last_used_fixed_point
        else:
            base_id = None
            if isinstance(base_id_or_list, list):
                for bid in base_id_or_list:
                    if bid in valid_kps:
                        base_id = bid
                        break
            elif base_id_or_list in valid_kps:
                base_id = base_id_or_list
            if base_id is None:
                return None
            base_pt = valid_kps[base_id]

        cx, cy = int(base_pt[0]), int(base_pt[1])

        drop_px = drop_cm * pixels_per_cm if pixels_per_cm > 0 else 30
        target_y = int(cy + drop_px)

        h, w = image_to_use.shape[:2]
        target_y = max(0, min(h - 1, target_y))

        # --- PREFERRED PATH: scan the solid mask row for the two legs ---
        if self._is_binary_mask(image_to_use):
            runs = self._row_runs(image_to_use, target_y)

            # Runs that belong to each leg, i.e. entirely on one side of the crotch.
            left_runs = [r for r in runs if r[1] <= cx]
            right_runs = [r for r in runs if r[0] >= cx]
            legs_are_separate = bool(left_runs and right_runs)

            if legs_are_separate:
                if leg == 'left':
                    run = left_runs[-1]
                    final_x = run[0] if edge == 'outer' else run[1]
                else:
                    run = right_runs[0]
                    final_x = run[1] if edge == 'outer' else run[0]

                final_pt = (int(final_x), target_y)
                self.debug_shapes.append({
                    'type': 'circle', 'center': final_pt, 'radius': 6, 'color': (255, 100, 100)
                })
                return final_pt

            if runs:
                # LEGS TOUCHING: at this height the two legs still form one shape, so the
                # inside edge of the leg is hidden underneath the other leg. The inseam runs
                # almost straight down from the crotch, so the crotch X is used as the inside
                # boundary - which is what an inspector does by hand when the legs overlap.
                #
                # ACCURACY NOTE: this makes the measurement depend on the crotch X being
                # correct. In production the operator aligns the crotch to the fixed reference
                # dot, so it is exact. With a plain photo it falls back to the AI keypoint,
                # which can sit off-centre. Separating the legs slightly when laying the
                # garment down removes this whole case.
                containing = [r for r in runs if r[0] <= cx <= r[1]] or [runs[0]]
                run = containing[0]
                if leg == 'left':
                    final_x = run[0] if edge == 'outer' else cx
                else:
                    final_x = run[1] if edge == 'outer' else cx

                final_pt = (int(final_x), target_y)
                self.debug_shapes.append({
                    'type': 'circle', 'center': final_pt, 'radius': 6, 'color': (0, 165, 255)
                })
                self.last_crotch_drop_note = (
                    "legs touching at the measuring height - inside edge estimated from the "
                    "crotch X; lay the garment with the legs slightly apart for best accuracy"
                )
                return final_pt

        # --- FALLBACK: narrow Canny slice, same technique as the shirt armpit drop ---
        search_x = int(data.get('search_px', 400))
        if leg == 'left':
            x_start, x_end = max(0, cx - search_x), cx
        else:
            x_start, x_end = cx, min(w, cx + search_x)

        y_min, y_max = max(0, target_y - 2), min(h, target_y + 3)
        roi = image_to_use[y_min:y_max, x_start:x_end]
        if roi.size == 0:
            return (cx, target_y)

        edges = cv2.Canny(cv2.GaussianBlur(roi, (3, 3), 0), 20, 80)
        roi_y, roi_x = np.where(edges > 0)
        if len(roi_x) == 0:
            return (cx, target_y)

        want_leftmost = (leg == 'left' and edge == 'outer') or (leg == 'right' and edge == 'inner')
        best_idx = np.argmin(roi_x) if want_leftmost else np.argmax(roi_x)
        return (int(x_start + roi_x[best_idx]), target_y)

    def get_final_point_location(self, p_input, valid_kps, image_gray, pixels_per_cm, logic_map, mask=None):
        """
        Calculates the final measurement point.
        COMPATIBILITY: Accepts 'mask' argument to prevent crashes from updated engine.
        """
        # NEW: Force the use of the solid mask if available
        image_to_use = mask if mask is not None else image_gray

        # CASE A: List of Candidates (Fallback Logic)
        if isinstance(p_input, list):
            for candidate_id in p_input:
                if candidate_id in valid_kps:
                    return self.get_final_point_location(candidate_id, valid_kps, image_gray, pixels_per_cm, logic_map, mask=mask)
            return None

        # CASE B: Simple Integer ID
        elif isinstance(p_input, int):
            if p_input not in valid_kps: return None
            pt = valid_kps[p_input]
            
            logic = self.get_point_refinement_logic(p_input, logic_map.get(p_input, 'center'))
            
            if logic == 'center':
                return pt
            
            # UPDATED: Use 'image_to_use' instead of 'image_gray'
            # TRIED: scaling this search box to real cm instead of a fixed 45px, to fix waist
            # corners reading too small. REVERTED (16 Sep 2026) - regression suite showed it
            # made things worse: a wider box grabbed wrong nearby edges (pockets, belt loops)
            # more often, and since Hip/Front Rise are built on these same corner points, that
            # cascaded into much bigger errors elsewhere (one Hip reading nearly halved).
            # The undersized-waist issue on real photos is still open; needs a more targeted fix
            # than just widening the search box.
            final_pt, _ = self.refine_point(image_to_use, pt[0], pt[1], logic, 45, 45)
            return final_pt

        # CASE C: Dictionary (Complex Logic)
        elif isinstance(p_input, dict):

            # --- CROTCH DROP LOGIC (thigh / any width N cm below the crotch) ---
            if 'crotch_drop' in p_input:
                return self.calculate_crotch_drop(
                    image_to_use, valid_kps, p_input['crotch_drop'], pixels_per_cm
                )

            # --- WAISTBAND TOP CENTRE (front rise / back rise) ---
            if 'waist_top_center' in p_input:
                return self.waist_top_center(valid_kps, image_gray, pixels_per_cm, logic_map,
                                             image_to_use, p_input['waist_top_center'])

            # --- HIP, 3-POINT METHOD ---
            if 'hip_3point' in p_input:
                return self.hip_3point(valid_kps, image_gray, pixels_per_cm, logic_map,
                                       image_to_use, p_input['hip_3point'])

            # --- FLY LENGTH (J-STITCH) ---
            if 'fly_j_stitch' in p_input:
                return self.fly_j_stitch(valid_kps, image_gray, pixels_per_cm, logic_map,
                                         image_to_use, p_input['fly_j_stitch'])

            base_id_or_list = p_input.get('base')
            base_id = None
            
            if isinstance(base_id_or_list, list):
                for bid in base_id_or_list:
                    if bid in valid_kps:
                        base_id = bid
                        break
            else:
                if base_id_or_list in valid_kps:
                    base_id = base_id_or_list

            if base_id is None: return None
            base_pt = valid_kps[base_id]
            
            scan_logic = p_input.get('find_edge', None)
            if not scan_logic:
                scan_logic = self.get_point_refinement_logic(base_id, logic_map.get(base_id, 'center'))

            if scan_logic == 'center':
                refined_pt = base_pt
            else:
                # UPDATED: Use 'image_to_use' instead of 'image_gray'
                refined_pt, _ = self.refine_point(image_to_use, base_pt[0], base_pt[1], scan_logic, 60, 25)
            
            # Apply shifts if needed
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

    def validate_measurements(self, measurements, valid_kps, config=None):
        issues = []
        # Basic sanity check: Waist (284) should be higher (lower Y) than hems (286)
        if 284 in valid_kps and 286 in valid_kps:
            waist_y = valid_kps[284][1]
            leg_y = valid_kps[286][1]
            if waist_y > leg_y: issues.append("Waist detected below leg - check orientation")
        return issues
    
    def draw_special_markers(self, image, valid_kps, g_config=None, fixed_point=None):
        """
        Draw markers on the final Result Image
        """
        pt_to_draw = fixed_point if fixed_point is not None else self.last_used_fixed_point

        # If we have a valid reference point, draw it clearly
        if pt_to_draw:
            cx, cy = pt_to_draw
            h, w = image.shape[:2]
            if 0 <= cx < w and 0 <= cy < h:
                cv2.circle(image, (cx, cy), 6, (0, 0, 255), -1)      # Red Dot
            else:
                cv2.putText(image, "REF OUT OF BOUNDS", (10, 50),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Draw the CROTCH alignment line
        if self.crotch_left in valid_kps and self.crotch_right in valid_kps:
            pt1 = valid_kps[self.crotch_left]
            pt2 = valid_kps[self.crotch_right]
            
            cv2.line(image, (int(pt1[0]), int(pt1[1])), (int(pt2[0]), int(pt2[1])), (255, 0, 255), 2)
            
            mid_x = int((pt1[0] + pt2[0]) / 2)
            mid_y = int(pt1[1])
            if not pt_to_draw:
                cv2.putText(image, "CROTCH", (mid_x - 30, mid_y - 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
        
        return image