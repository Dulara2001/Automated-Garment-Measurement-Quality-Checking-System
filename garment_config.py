"""
Configuration for GarmentQC AI
Defines measurement logic, point maps, and size standards.
"""
import json
import os

# =========================================================
# MEASUREMENT LETTER MAPPINGS (JSON REFERENCE)
# =========================================================
# --- SHIRT / TOP ---
# A - Neck Width
# B - Sleeve Opening - Short
# C - CPSC - Chest Armpit to Armpit
# D - CF Body Length (HPS to Bottom Edge)
# E - CPSC - Bottom Sweep Straight (CPSC Waist)
# F - Sleeve Length from Shoulder Seam
# G - CPSC - Upper Arm
# H - Shoulder Width (Manual/UI)
# z - Shoulder Width (Auto-detected)
# I - CPSC - Upper Arm Position - 2 Piece
# J - Side Seam Right (Armpit to Hem)
#
# --- TROUSERS ---
# J - Waist Width
# K - Left Leg Opening
# L - Right Leg Opening
# M - Hip Width
# N - Left Leg Length
# O - Right Leg Length
# P - Right Inseam
# Q - Left Inseam
# R - Left leg width at knee
# S - Rise (front)
# T - Thigh (1" below crotch)          [ADDED for customer POM L-02]
# U - Back Rise                        [ADDED for customer POM K-05, needs the BACK view]
# V - Fly Length (J stitch)            [ADDED for customer POM N-01, EXPERIMENTAL]
#
# CUSTOMER POM MAPPING (spec sheet "3889 and pant Spec")
#   Put the customer's code in the "pom_code" field of size_standards.json and the
#   letter below in "description", which is what the engine matches on.
#
#   H-50 Waist           -> J        L-02 Thigh          -> T
#   I-26 Hip             -> M        L-38 Bottom opening -> K (left) and L (right)
#   K-01 Front rise      -> S        A-64 Inseam         -> P (right) and Q (left)
#   K-05 Back rise       -> U        N-01 Fly length     -> V (experimental)
# =========================================================

# =========================================================
# 0. KEYPOINT VARIABLES
# =========================================================
# -- SHIRT / TOP POINTS --
TOP_NECK_L          = [257]        
TOP_NECK_R          = [261]        
TOP_SHOULDER_HPS    = [290]        
TOP_SHOULDER_R      = [293]
TOP_SHOULDER_L      = [225]
TOP_ARM_OPEN_TOP_L  = [229]        
TOP_ARM_OPEN_BTM_L  = [230, 231] 
TOP_ARM_OPEN_TOP_R  = [251, 252]   
TOP_ARM_OPEN_BTM_R  = [250]        
TOP_ARMPIT_L        = [234,276]        
TOP_ARMPIT_R        = [246]        
TOP_HEM_L           = [286]        
TOP_HEM_R           = [288]        
TOP_HEM_CENTER      = [269]  

# -- TSHIRT RIGHT EDGES --
SEAM_POINTS_R = [155, 290, 291]

# -- TROUSER POINTS --
PANT_WAIST_L        = [284]
PANT_WAIST_R        = [290]
PANT_HEM_L_OUTER    = [286] 
PANT_HEM_L_INNER    = [174] 
PANT_HEM_R_OUTER    = [288] 
PANT_HEM_R_INNER    = [250] 
PANT_HIP_R          = [257]
PANT_HIP_L          = [282]
PANT_CROTCH         = [234] 
PANT_RISE_TOP       = [278] 
PANT_KNEE_1         = [229]
PANT_KNEE_2         = [276]
PANT_EXTRA_1        = [199]
PANT_EXTRA_2        = [287]

# =========================================================
# 1. LOGIC GENERATOR
# =========================================================
def register_points(logic_dict, id_list, logic_type):
    for pid in id_list:
        logic_dict[pid] = logic_type
    return logic_dict

_top_logic = {}
# --- SHIRT LOGIC ---
register_points(_top_logic, TOP_NECK_L, 'top_most')         
register_points(_top_logic, TOP_NECK_R, 'top_most')         
register_points(_top_logic, TOP_SHOULDER_R, 'top_right')
register_points(_top_logic, TOP_SHOULDER_L, 'top_left')    
register_points(_top_logic, TOP_SHOULDER_HPS, 'top_most')    
register_points(_top_logic, TOP_ARM_OPEN_TOP_L, 'left_most')     
register_points(_top_logic, TOP_ARM_OPEN_BTM_L, 'bottom_most')   
register_points(_top_logic, TOP_ARM_OPEN_TOP_R, 'right_most')    
register_points(_top_logic, TOP_ARM_OPEN_BTM_R, 'bottom_most_right')  
register_points(_top_logic, TOP_ARMPIT_L, 'armpit_left')      
register_points(_top_logic, TOP_ARMPIT_R, 'armpit_right')     
register_points(_top_logic, TOP_HEM_L, 'bottom_left')       
register_points(_top_logic, TOP_HEM_R, 'bottom_right')      
register_points(_top_logic, TOP_HEM_CENTER, 'bottom_most')

# --- TROUSER LOGIC ---
_pant_logic = {}
register_points(_pant_logic, PANT_WAIST_L, 'top_left')      
register_points(_pant_logic, PANT_WAIST_R, 'top_right')     
register_points(_pant_logic, PANT_HEM_L_OUTER, 'bottom_left') 
register_points(_pant_logic, PANT_EXTRA_1, 'bottom_right')    
register_points(_pant_logic, PANT_HEM_R_OUTER, 'bottom_right') 
register_points(_pant_logic, PANT_EXTRA_2, 'bottom_right')    
register_points(_pant_logic, PANT_HIP_R, 'right_most')        
register_points(_pant_logic, PANT_HIP_L, 'left_most')         
register_points(_pant_logic, PANT_HEM_R_INNER, 'bottom_left') 
register_points(_pant_logic, PANT_HEM_L_INNER, 'bottom_right') 

# =========================================================
# 2. DEFINITIONS (Reusable Logic Blocks)
# =========================================================
LOGIC_NECK_LOW_POINT = {
    'base': TOP_NECK_L, 
    'find_edge': 'top_most', 
    'circular_intersect': {'radius_cm': 1.7, 'side': 'left'}
}

LOGIC_NECK_HPS_RAW = {
    'base': TOP_NECK_L, 
    'find_edge': 'top_most'
}

LOGIC_UPPER_ARM_R_TOP = {
    'upper_arm_parallel': {
        'seam_points': SEAM_POINTS_R, 
        'seam_refine_logic': 'right_most',
        'sleeve_top_pt': TOP_ARM_OPEN_TOP_R,
        'sleeve_open_ref': [TOP_ARM_OPEN_TOP_R, TOP_ARM_OPEN_BTM_R],
        'top_refine': 'right_most',
        'btm_refine': 'bottom_right',
        'return': 'top',
        'side': 'right' 
    }
}

LOGIC_UPPER_ARM_R_BTM = {
    'upper_arm_parallel': {
        'seam_points': SEAM_POINTS_R, 
        'seam_refine_logic': 'right_most',
        'sleeve_top_pt': TOP_ARM_OPEN_TOP_R,
        'sleeve_open_ref': [TOP_ARM_OPEN_TOP_R, TOP_ARM_OPEN_BTM_R],
        'top_refine': 'right_most',
        'btm_refine': 'bottom_right',
        'return': 'bottom',
        'side': 'right'
    }
}

LOGIC_SIDE_SEAM_INTERSECT_R = {
    'upper_arm_parallel': {
        'seam_points': SEAM_POINTS_R, 
        'seam_refine_logic': 'right_most',
        'sleeve_top_pt': TOP_ARM_OPEN_TOP_R,
        'sleeve_open_ref': [TOP_ARM_OPEN_TOP_R, TOP_ARM_OPEN_BTM_R],
        'top_refine': 'right_most',
        'btm_refine': 'bottom_right',
        'return': 'intersect', 
        'side': 'right' 
    }
}

LOGIC_ARMPIT_DROP_L = {
    'armpit_drop': {
        'base': TOP_ARMPIT_L,
        'drop_cm': 0.5,
        'refine_logic': 'top_right'
    }
}

LOGIC_ARMPIT_DROP_R = {
    'armpit_drop': {
        'base': TOP_ARMPIT_R,
        'drop_cm': 0.2,
        'refine_logic': 'top_left'
    }
}

# --- SHOULDER DEFINITIONS ---
LOGIC_RIGHT_SHOULDER_MANUAL = {
    'manual_shoulder': {
        'base': TOP_SHOULDER_R
    }
}

LOGIC_RIGHT_SHOULDER_AUTO = {
    'shoulder_corner': {
        'base': TOP_SHOULDER_R, 
        'side': 'right'
    }
}

# NEW: Left Shoulder Auto using the exact same corner-finding algorithm
LOGIC_LEFT_SHOULDER_AUTO = {
    'shoulder_corner': {
        'base': TOP_SHOULDER_L, 
        'side': 'left'
    }
}

LOGIC_LATEST_SHOULDER = {
    'use_latest_shoulder': True
}

LOGIC_LEFT_SHOULDER_DYNAMIC_MANUAL = {
    'dynamic_left_shoulder': {
        'base_right_shoulder': LOGIC_RIGHT_SHOULDER_MANUAL
    }
}
# ------------------------------------

# --- TROUSER: THIGH (customer POM L-02) ---
# "Measure straight across the width, 2.5cm/1in below crotch seam, at 90 deg to the inside
#  leg." Handled by TrouserProcessor.calculate_crotch_drop(): drop below the crotch, then
#  snap sideways to each edge of the leg while keeping the exact Y.
# =========================================================
# PANT POM SETTINGS  (customer spec "3889 and pant Spec")
# =========================================================
# Crotch: "auto" finds the real crotch from the silhouette + AI point and uses the red dot
# only as a cross-check. "fixed_dot" is the original behaviour (trust the operator's alignment).
TROUSER_CROTCH_MODE = "auto"

# Clean up the U2-Net outline for trousers by removing table-coloured pixels. U2-Net runs at
# 320x320 and can fill in the gap between the legs, which hides the crotch and the inner hem corners.
TROUSER_MASK_REFINE = True

# Measurements that may be missing without forcing a retake (experimental ones).
TROUSER_OPTIONAL_CODES = ["V"]

# Hip (I-26) placement down the rise seam. NOT CONFIRMED BY THE CUSTOMER.
# Set HIP_DROP_CM to an exact distance below the waistband top once known; until then the hip
# line is placed at HIP_RISE_FRACTION of the rise (0.75 = three quarters of the way down).
HIP_DROP_CM = None
HIP_RISE_FRACTION = 0.75   # ASSUMPTION

THIGH_DROP_CM = 2.54   # 1 inch. Change here if the customer specifies a different drop.

LOGIC_THIGH_OUTER_L = {
    'crotch_drop': {
        'base': PANT_CROTCH,
        'drop_cm': THIGH_DROP_CM,
        'leg': 'left',
        'edge': 'outer'
    }
}

LOGIC_WAIST_TOP_CENTER = {
    'waist_top_center': {
        'left': PANT_WAIST_L[0],
        'right': PANT_WAIST_R[0]
    }
}

LOGIC_HIP_LEFT = {
    'hip_3point': {
        'side': 'left',
        'waist_left': PANT_WAIST_L[0],
        'waist_right': PANT_WAIST_R[0],
        'drop_cm': HIP_DROP_CM,
        'rise_fraction': HIP_RISE_FRACTION
    }
}

LOGIC_HIP_RIGHT = {
    'hip_3point': {
        'side': 'right',
        'waist_left': PANT_WAIST_L[0],
        'waist_right': PANT_WAIST_R[0],
        'drop_cm': HIP_DROP_CM,
        'rise_fraction': HIP_RISE_FRACTION
    }
}

LOGIC_FLY_TOP = {'fly_j_stitch': {'return': 'top'}}
LOGIC_FLY_BOTTOM = {'fly_j_stitch': {'return': 'bottom'}}

LOGIC_THIGH_INNER_L = {
    'crotch_drop': {
        'base': PANT_CROTCH,
        'drop_cm': THIGH_DROP_CM,
        'leg': 'left',
        'edge': 'inner'
    }
}
# ------------------------------------

# =========================================================
# 3. CONFIGURATION OBJECT
# =========================================================
GARMENT_CONFIG = {
    'short_sleeve_top': {
        'display_name': 'Short Sleeve Top',
        'point_logic': _top_logic,
        
        'point_candidates': {
            'neck_left': TOP_NECK_L,
            'neck_right': TOP_NECK_R,
            'shoulder_right': TOP_SHOULDER_R,
            'shoulder_left': TOP_SHOULDER_L,
            'arm_open_top_r': TOP_ARM_OPEN_TOP_R,
            'arm_open_btm_r': TOP_ARM_OPEN_BTM_R,
            'hem_left': TOP_HEM_L,
            'hem_right': TOP_HEM_R
        },
        'zone_config': {
            'left_zone': TOP_ARM_OPEN_BTM_L + TOP_ARM_OPEN_TOP_L + TOP_HEM_L + TOP_NECK_L + TOP_ARMPIT_L + TOP_SHOULDER_L,
            'right_zone': TOP_ARM_OPEN_BTM_R + TOP_ARM_OPEN_TOP_R + TOP_HEM_R + TOP_NECK_R + TOP_SHOULDER_R + TOP_ARMPIT_R
        },
        'measurements': [
            (
                LOGIC_NECK_LOW_POINT, 
                {'base': TOP_NECK_R, 'find_edge': 'top_most', 'circular_intersect': {'radius_cm': 2, 'side': 'right'}}, 
                "A"  # Neck Width
            ),
            (LOGIC_LEFT_SHOULDER_DYNAMIC_MANUAL, LOGIC_RIGHT_SHOULDER_MANUAL, "H"),  # Manual/UI-driven Shoulder Width
            (LOGIC_LEFT_SHOULDER_AUTO, LOGIC_RIGHT_SHOULDER_AUTO, "Z"),              # FIXED: Pure Auto-detected Left AND Right Shoulder Corners
            (LOGIC_LATEST_SHOULDER, TOP_ARM_OPEN_TOP_R, "F"),                        # SMART Sleeve Length (Automatically uses H or Z point)
            (LOGIC_ARMPIT_DROP_L, LOGIC_ARMPIT_DROP_R, "C"),                         # CPSC - Chest Armpit to Armpit
            (
                LOGIC_NECK_LOW_POINT,
                {
                    'perpendicular_projection': {
                        'source': LOGIC_NECK_LOW_POINT,
                        'line_p1': TOP_HEM_L,
                        'line_p2': TOP_HEM_R
                    }
                }, 
                "D"  # CF Body Length (HPS to Bottom Edge)
            ),
            (TOP_ARM_OPEN_TOP_R, TOP_ARM_OPEN_BTM_R, "B"),                           # Sleeve Opening - Short
            (TOP_ARM_OPEN_TOP_L, TOP_ARM_OPEN_BTM_L, "B"),                           # Left Sleeve Opening
            (LOGIC_UPPER_ARM_R_TOP, LOGIC_UPPER_ARM_R_BTM, "G"),                     # CPSC - Upper Arm
            (LOGIC_ARMPIT_DROP_R, LOGIC_SIDE_SEAM_INTERSECT_R, "Armpit to Sleeve Top Edge (Right)"), # Debug Line
            (TOP_HEM_L, TOP_HEM_R, "E"),                                             # CPSC - Bottom Sweep Straight (CPSC Waist)
            (LOGIC_ARMPIT_DROP_R, TOP_HEM_R, "J")                                    # Side Seam Right (Armpit to Hem)
        ]
    },

    'trousers': {
        'display_name': 'Trousers',
        'point_logic': _pant_logic,
        'zone_config': {
            'left_zone': PANT_WAIST_L + PANT_HEM_L_OUTER + PANT_EXTRA_2 + PANT_HIP_L + PANT_HEM_L_INNER,
            'right_zone': PANT_WAIST_R + PANT_HEM_R_OUTER + PANT_HIP_R + PANT_HEM_R_INNER + PANT_EXTRA_1
        },
        'measurements': [
            (PANT_WAIST_L, PANT_WAIST_R, "J"),               # Waist Width
            (PANT_HEM_L_OUTER, PANT_HEM_L_INNER, "K"),       # Left Leg Opening
            (PANT_HEM_R_OUTER, PANT_HEM_R_INNER, "L"),       # Right Leg Opening
            (LOGIC_HIP_LEFT, LOGIC_HIP_RIGHT, "M"),          # Hip, 3-point method (POM I-26)
            (PANT_WAIST_L, PANT_HEM_L_OUTER, "N"),           # Left Leg Length
            (PANT_HEM_R_OUTER, PANT_WAIST_R, "O"),           # Right Leg Length
            (PANT_HEM_R_INNER, PANT_CROTCH, "P"),            # Right Inseam
            (PANT_HEM_L_INNER, PANT_CROTCH, "Q"),            # Left Inseam
            (PANT_KNEE_1, PANT_KNEE_2, "R"),                 # Left leg width at knee
            (PANT_CROTCH, LOGIC_WAIST_TOP_CENTER, "S"),      # Front Rise, waistband top centre (POM K-01)
            (LOGIC_THIGH_OUTER_L, LOGIC_THIGH_INNER_L, "T"), # Thigh 1" below crotch, 90 deg to inside leg (POM L-02)
            (LOGIC_FLY_TOP, LOGIC_FLY_BOTTOM, "V")           # Fly length to bottom of J stitch (POM N-01, EXPERIMENTAL)
        ]
    },

    # =====================================================================
    # BACK VIEW OF TROUSERS
    # Back Rise (customer POM K-05) is on the back of the garment, so it cannot be seen in
    # the normal front capture. The operator flips the trousers over and captures again with
    # this garment type selected. Everything else (engine, QC, sync) is unchanged.
    # NOTE: the customer's rule measures ALONG THE CURVE of the back rise; the engine only
    # measures straight lines between two points, so this reads slightly short. Confirm the
    # tolerance with the customer or add a curve-following logic rule.
    # =====================================================================
    'trousers_back': {
        'display_name': 'Trousers (Back View)',
        'point_logic': _pant_logic,
        'zone_config': {
            'left_zone': PANT_WAIST_L + PANT_HEM_L_OUTER + PANT_EXTRA_2 + PANT_HIP_L + PANT_HEM_L_INNER,
            'right_zone': PANT_WAIST_R + PANT_HEM_R_OUTER + PANT_HIP_R + PANT_HEM_R_INNER + PANT_EXTRA_1
        },
        'measurements': [
            (PANT_WAIST_L, PANT_WAIST_R, "J"),               # Waist again, as a cross-check
            (PANT_CROTCH, LOGIC_WAIST_TOP_CENTER, "U")       # Back Rise (POM K-05)
        ]
    }
}

KEY_MEASUREMENTS = {
    'short_sleeve_top': ["A", "H", "Z", "F", "B", "I", "G", "C", "E", "D", "J"],
    # NOTE: these are CASE SENSITIVE and are matched against the measurement codes above.
    # A lowercase entry here silently drops that measurement from the results.
    'trousers': ["J", "N", "M", "P", "Q", "R", "S", "T", "V", "L", "K", "O"],
    'trousers_back': ["J", "U"]
}

# =========================================================
# 4. SIZE STANDARDS (DEFAULTS + JSON LOADER)
# =========================================================
SIZE_STANDARDS = {
  "units": "inch", 
  "short_sleeve_top": {},
  "trousers": {}
}

# Attempt to load external JSON file to populate/override standards
try:
    paths_to_check = ["data/size_standards.json", "size_standards.json"]
    loaded_data = None
    
    for p in paths_to_check:
        if os.path.exists(p):
            with open(p, 'r') as f:
                content = f.read().strip()
                if content:
                    loaded_data = json.loads(content)
                    print(f"[GarmentConfig] Loaded standards from {p}")
            break
            
    if loaded_data:
        SIZE_STANDARDS.update(loaded_data)
        if "key_measurements" in loaded_data:
            KEY_MEASUREMENTS.update(loaded_data["key_measurements"])

        # --- ADD THIS NEW BLOCK TO FETCH COLLAR SIZE ---
        try:
            # 1. Access the 'short_sleeve_top' data and grab the first available size (e.g., '4T')
            sst_standards = SIZE_STANDARDS.get("short_sleeve_top", {})
            if sst_standards:
                first_size_key = list(sst_standards.keys())[0] 
                measurements_list = sst_standards[first_size_key]

                # 2. Loop through to find pom_code "SL0011"
                for item in measurements_list:
                    if item.get("name") == "Collar Size" :
                        # item.get("pom_code") == "SL0011":
                        # Extract only the value and convert it to a float
                        raw_collar_value = float(item["value"])
                        
                        # 3. Convert inches to cm (since your logic uses radius_cm)
                        units = SIZE_STANDARDS.get("units", "inch").lower()
                        collar_radius_cm = raw_collar_value * 2.54 if units == "inch" else raw_collar_value

                        # 4. Replace the hardcoded 1.7 in LOGIC_NECK_LOW_POINT
                        LOGIC_NECK_LOW_POINT['circular_intersect']['radius_cm'] = collar_radius_cm
                        
                        # Optional: Replace the hardcoded '2' for the right side in GARMENT_CONFIG's measurement array
                        GARMENT_CONFIG['short_sleeve_top']['measurements'][0][1]['circular_intersect']['radius_cm'] = collar_radius_cm
                        
                        print(f"[GarmentConfig] Dynamically updated neck radius_cm to {collar_radius_cm:.4f}")
                        break
        except Exception as e:
            print(f"[GarmentConfig] Warning: Could not parse Collar Size from JSON: {e}")
        # --- END NEW BLOCK ---

except Exception as e:
    print(f"[GarmentConfig] Warning: Could not load size_standards.json. Using internal defaults. Error: {e}")