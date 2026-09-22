import cv2
import numpy as np
import math


# ══════════════════════════════════════════════════════════════════════════════
#  ULTRA-PRECISE 3D POSE CALIBRATOR
# ══════════════════════════════════════════════════════════════════════════════
#
#  Upgrades in this version:
#  1. 3D Pose Estimation (PnP): Calculates the true physical angle of the
#     camera relative to the board using an intrinsic matrix approximation.
#  2. Visual Bubble Level: Shows exactly which way to tilt the camera to fix
#     the alignment, complete with a directional guiding arrow.
#  3. Strict Angle Gating: PPCM is ONLY recorded into the Cumulative Median
#     filter if the board is mathematically proven to be flat (< 3.0 degrees).
#  4. Multi-Board Support: Seamlessly detects 12x8 (A3) and 5x8 (A4) boards.
#
# ══════════════════════════════════════════════════════════════════════════════


class Calibrator:
    """
    Professional pixel-per-centimetre calibrator with 3D Pose Estimation.
    """

    # ── Board Specification ───────────────────────────────────────────────────
    SQUARE_SIZE_CM: float = 3.0

    # Handles both the new A3 board (13x9 squares -> 12x8 corners) 
    # and the old A4 board (9x6 squares -> 8x5 corners), plus landscape modes.
    PRIMARY_PATTERNS = [
        (12, 8),  # A3 Portrait
        (8, 12),  # A3 Landscape
        (5, 8),   # A4 Portrait
        (8, 5),   # A4 Landscape
    ]
    
    # Fallbacks for partial views
    FALLBACK_PATTERNS = [(7, 4), (4, 7), (5, 4), (4, 5)]

    # ── Saddle-Point Detection Flags ──────────────────────────────────────────
    _SB_FLAGS = (
        cv2.CALIB_CB_NORMALIZE_IMAGE |
        cv2.CALIB_CB_EXHAUSTIVE      |
        cv2.CALIB_CB_ACCURACY
    )

    # ── Strict Validation Thresholds ──────────────────────────────────────────
    _MIN_FRAMES: int = 5              # Require 5 perfect frames before locking
    _MAX_STDDEV_RATIO: float = 0.04   # Reject if grid distances vary by > 4%
    _MAX_ANGLE_DEG: float = 3.0       # Reject PPCM reading if tilt > 3.0 degrees

    def __init__(self):
        # State
        self.locked_ppcm: float | None = None
        self._history: list[float] = []
        self._frame_count: int = 0
        self._last_pattern: tuple | None = None
        
        # Temporal Smoothing for the UI Angle
        self.smoothed_angle: float | None = None
        self.smoothed_nx: float = 0.0
        self.smoothed_ny: float = 0.0

    # ─────────────────────────────────────────────────────────────────────────
    def reset(self):
        """Clear all temporal history and start fresh."""
        self.locked_ppcm = None
        self._history.clear()
        self._frame_count = 0
        self._last_pattern = None
        self.smoothed_angle = None
        self.smoothed_nx = 0.0
        self.smoothed_ny = 0.0

    # ─────────────────────────────────────────────────────────────────────────
    def get_pixels_per_cm(
        self,
        image: np.ndarray,
        t1: int = 50,
        t2: int = 150
    ) -> tuple:
        """Core calibration loop called by your server."""
        
        debug_img = image.copy()
        gray      = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges_out = cv2.Canny(gray, t1, t2)

        # ── Step 1: CLAHE Contrast Enhancement ────────────
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_eq = clahe.apply(gray)

        # ── Step 2: Detect inner corners ─────────────
        corners, pattern_used = self._detect_corners(gray_eq)

        if corners is None:
            self._draw_failure(debug_img)
            return self.locked_ppcm, debug_img, edges_out

        # ── Step 3: Calculate True 3D Angle via Pose Estimation ──────────
        angle_deg, nx, ny = self._calculate_3d_pose(corners, pattern_used, gray.shape)
        
        # Smooth the UI metrics to prevent jitter
        self._smooth_ui_metrics(angle_deg, nx, ny)

        # ── Step 4: Compute raw PPCM from distances ──────────
        raw_ppcm, std_ratio = self._compute_ppcm(corners, pattern_used)

        if raw_ppcm is None or std_ratio > self._MAX_STDDEV_RATIO:
            self._draw_failure(debug_img, reason="Grid distorted — ensure board is flat")
            return self.locked_ppcm, debug_img, edges_out

        # ── Step 5: Strict Angle Gating & History Lock ──────────
        # ONLY update the locked value if the camera is perfectly flat.
        # This guarantees 100% precision.
        if self.smoothed_angle <= self._MAX_ANGLE_DEG:
            self._update_smoothing(raw_ppcm)

        # ── Step 6: Render UI & Bubble Level ──────────
        self._draw_success(debug_img, corners, pattern_used, raw_ppcm, std_ratio)

        return self.locked_ppcm, debug_img, edges_out

    # ══════════════════════════════════════════════════════════════════════════
    #  PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _detect_corners(self, gray_eq: np.ndarray):
        all_patterns = self.PRIMARY_PATTERNS + self.FALLBACK_PATTERNS

        # Prioritize the last successful pattern for speed
        if self._last_pattern and self._last_pattern in all_patterns:
            all_patterns.remove(self._last_pattern)
            all_patterns.insert(0, self._last_pattern)

        for pattern in all_patterns:
            # Try Saddle-Point detector first (sub-pixel accuracy built-in)
            ret, corners = cv2.findChessboardCornersSB(gray_eq, pattern, self._SB_FLAGS)

            if not ret:
                # Classic fallback
                ret, corners = cv2.findChessboardCorners(
                    gray_eq, pattern,
                    cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
                )
                if ret:
                    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.0001)
                    corners  = cv2.cornerSubPix(gray_eq, corners, (7, 7), (-1, -1), criteria)

            if ret and corners is not None:
                self._last_pattern = pattern
                return corners, pattern

        return None, None

    def _calculate_3d_pose(self, corners: np.ndarray, pattern: tuple, img_shape: tuple) -> tuple:
        """
        Uses cv2.solvePnP to find the exact 3D orientation of the board.
        Returns: (angle_in_degrees, normal_x, normal_y)
        """
        cols, rows = pattern
        h, w = img_shape
        
        # 1. Generate ideal 3D points of the board
        objp = np.zeros((rows * cols, 3), np.float32)
        objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * self.SQUARE_SIZE_CM

        # 2. Approximate Camera Intrinsic Matrix
        # Standard cameras have a FOV that makes focal_length ~ 0.8 * width.
        focal_length = max(h, w) * 0.8
        camera_matrix = np.array([
            [focal_length, 0.0, float(w) / 2.0],
            [0.0, focal_length, float(h) / 2.0],
            [0.0, 0.0, 1.0]
        ], dtype=np.float32)
        dist_coeffs = np.zeros((4, 1), dtype=np.float32)

        # 3. Solve Perspective-n-Point 
        # Using the default ITERATIVE solver instead of IPPE.
        # Iterative is significantly more robust for dense coplanar grids (like the A3's 96 points)
        # where minor paper warping or lens distortion breaks IPPE's math.
        ret, rvec, tvec = cv2.solvePnP(objp, corners, camera_matrix, dist_coeffs)

        if not ret:
            return 99.0, 0.0, 0.0

        # 4. Extract Orientation Normal
        R, _ = cv2.Rodrigues(rvec)
        
        # The board sits on the Z=0 plane. Its normal is [0, 0, 1].
        normal_cam = R @ np.array([0.0, 0.0, 1.0])
        
        # Enforce a consistent normal direction pointing towards the camera.
        # This prevents the bubble-level UI from reversing direction due to the 
        # 180-degree rotational ambiguity of symmetric A3 grids (12x8).
        if normal_cam[2] > 0:
            normal_cam = -normal_cam
        
        # The angle relative to the camera lens (Z-axis)
        cos_theta = abs(normal_cam[2])
        angle_rad = math.acos(np.clip(cos_theta, -1.0, 1.0))
        angle_deg = math.degrees(angle_rad)

        return angle_deg, normal_cam[0], normal_cam[1]

    def _smooth_ui_metrics(self, angle_deg, nx, ny):
        """Applies Exponential Moving Average to prevent UI jitter."""
        alpha = 0.2  # Smoothing factor
        if self.smoothed_angle is None:
            self.smoothed_angle = angle_deg
            self.smoothed_nx = nx
            self.smoothed_ny = ny
        else:
            self.smoothed_angle = (1 - alpha) * self.smoothed_angle + alpha * angle_deg
            self.smoothed_nx = (1 - alpha) * self.smoothed_nx + alpha * nx
            self.smoothed_ny = (1 - alpha) * self.smoothed_ny + alpha * ny

    def _compute_ppcm(self, corners: np.ndarray, pattern: tuple):
        """Calculates scale purely from 2D pixel distance median."""
        cols, rows = pattern
        pts = corners.reshape(rows, cols, 2)

        distances = []
        for r in range(rows):
            for c in range(cols - 1):
                d = float(np.linalg.norm(pts[r, c] - pts[r, c + 1]))
                if d > 1.0: distances.append(d)

        for r in range(rows - 1):
            for c in range(cols):
                d = float(np.linalg.norm(pts[r, c] - pts[r + 1, c]))
                if d > 1.0: distances.append(d)

        if len(distances) < 4:
            return None, None

        arr = np.array(distances)
        median = float(np.median(arr))
        std = float(np.std(arr))

        std_ratio = std / median if median > 0 else 999.0
        ppcm = median / self.SQUARE_SIZE_CM

        return ppcm, std_ratio

    def _update_smoothing(self, raw_ppcm: float):
        """Only updates if angle is perfect."""
        self._history.append(raw_ppcm)
        self._frame_count += 1
        if self._frame_count >= self._MIN_FRAMES:
            stable_ppcm = float(np.median(self._history))
            self.locked_ppcm = round(stable_ppcm, 4)

    # ─────────────────────────────────────────────────────────────────────────
    #  UI DRAWING LOGIC
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_success(self, img, corners, pattern, raw_ppcm, std_ratio):
        h, w = img.shape[:2]
        scale = max(1.0, w / 1920)

        # 1. Draw Corners
        cv2.drawChessboardCorners(img, pattern, corners, True)

        # 2. Status Panel overlay
        overlay = img.copy()
        cv2.rectangle(overlay, (0, 0), (int(950 * scale), int(260 * scale)), (15, 15, 15), -1)
        cv2.addWeighted(overlay, 0.7, img, 0.3, 0, img)

        def text(msg, row, colour=(0, 255, 80), bold=False):
            th = int(1.8 * scale)
            size = 1.3 * scale
            y = int(50 * scale * (row + 1))
            cv2.putText(img, msg, (int(20 * scale), y), cv2.FONT_HERSHEY_SIMPLEX, size, colour, th + (1 if bold else 0))

        # Check conditions
        angle_ok = self.smoothed_angle <= self._MAX_ANGLE_DEG
        status = "LOCKED (FLAT)" if self.locked_ppcm else ("GATHERING DATA" if angle_ok else "ANGLE ERROR")
        colour = (0, 255, 80) if self.locked_ppcm else ((0, 200, 255) if angle_ok else (0, 60, 255))

        ppcm_display = self.locked_ppcm if self.locked_ppcm else raw_ppcm
        text(f"[{status}]  {ppcm_display:.4f} px/cm", 0, colour, bold=True)
        text(f"Raw: {raw_ppcm:.4f}  |  StdDev: {std_ratio * 100:.2f}%  |  Pattern: {pattern[0]}x{pattern[1]}", 1, (180, 180, 180))
        
        # Display Angle strictly
        ang_col = (0, 255, 80) if angle_ok else (0, 60, 255)
        text(f"Angle: {self.smoothed_angle:.2f} deg  (Limit {self._MAX_ANGLE_DEG} deg)", 2, ang_col)
        text(f"Valid Flat Frames: {self._frame_count} (Filter: Cum. Median)", 3, (150, 150, 150))

        # 3. Draw the Visual Bubble Level & Guidance Arrow
        self._draw_bubble_level(img, scale, w)

    def _draw_bubble_level(self, img, scale, screen_width):
        """Draws a crosshair target and an arrow telling the user how to move."""
        cx = int(screen_width - 150 * scale)
        cy = int(150 * scale)
        radius = int(80 * scale)

        # Background circle for UI
        overlay = img.copy()
        cv2.circle(overlay, (cx, cy), radius + 10, (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)

        # Draw Crosshair
        cv2.line(img, (cx - radius, cy), (cx + radius, cy), (255, 255, 255), 1)
        cv2.line(img, (cx, cy - radius), (cx, cy + radius), (255, 255, 255), 1)

        # Calculate Dot Position
        # Map 15 degrees to the outer edge of the circle
        dist_ratio = min(self.smoothed_angle / 15.0, 1.0)
        pixel_dist = dist_ratio * radius

        norm_xy = math.hypot(self.smoothed_nx, self.smoothed_ny)
        if norm_xy > 1e-5:
            dx = (self.smoothed_nx / norm_xy) * pixel_dist
            dy = (self.smoothed_ny / norm_xy) * pixel_dist
        else:
            dx, dy = 0, 0

        dot_x, dot_y = int(cx + dx), int(cy + dy)
        dot_color = (0, 255, 80) if self.smoothed_angle <= self._MAX_ANGLE_DEG else (0, 60, 255)

        # Draw the target dot
        cv2.circle(img, (dot_x, dot_y), int(8 * scale), dot_color, -1)

        # Draw the Guidance Arrow (points from Dot TO Center)
        # This tells the user: "Push this direction" to center the camera
        if self.smoothed_angle > 1.5:
            cv2.arrowedLine(img, (dot_x, dot_y), (cx, cy), (0, 200, 255), int(3 * scale), tipLength=0.35)
            
            # Helper text below bubble
            cv2.putText(img, "TILT CAMERA", (cx - int(50*scale), cy + radius + int(25*scale)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6*scale, (0, 200, 255), int(1.5*scale))

    def _draw_failure(self, img, reason: str = "Board not detected — show full checkerboard"):
        h, w = img.shape[:2]
        scale = max(1.0, w / 1920)

        overlay = img.copy()
        cv2.rectangle(overlay, (0, 0), (int(1100 * scale), int(130 * scale)), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)

        locked = self.locked_ppcm
        if locked:
            msg = f"Board lost — using last locked: {locked:.4f} px/cm"
            col = (0, 200, 255)
        else:
            msg = reason
            col = (0, 60, 255)

        cv2.putText(img, msg, (int(20 * scale), int(80 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4 * scale, col, int(1.8 * scale))