"""
GarmentQC AI - Professional Splash Theme (Slideshow & Secure Version Edition)
Location: loading/splash_theme.py
"""
import os
import base64
import glob
import json

# --- ENCRYPTION CONFIGURATION ---
ENCRYPTION_KEY = b"REDACTED_ROTATED_KEY"
VERSION_FILE_NAME = "sys_config_v1.bin"

def xor_crypt(data):
    """Decrypts (or encrypts) the version file data."""
    key_len = len(ENCRYPTION_KEY)
    return bytearray(b ^ ENCRYPTION_KEY[i % key_len] for i, b in enumerate(data))

def get_app_version():
    """Reads and decrypts the hidden version file."""
    try:
        # Resolve path whether running from source or compiled EXE
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        version_path = os.path.join(base_path, VERSION_FILE_NAME)
        
        # Fallback if running directly in IDE
        if not os.path.exists(version_path):
            version_path = VERSION_FILE_NAME
            
        if os.path.exists(version_path):
            with open(version_path, "rb") as f:
                encrypted_data = f.read()
            
            # Decrypt back to JSON string
            decrypted_data = xor_crypt(encrypted_data)
            data = json.loads(decrypted_data.decode('utf-8'))
            return data.get("version", "1.0.0")
    except Exception as e:
        print(f"[Theme Warning] Could not read encrypted version file: {e}")
    return "1.0.0" # Fallback if missing or corrupt

APP_VERSION = get_app_version()

def get_all_images():
    """
    Scans the current directory for ALL .png and .jpg files.
    Returns a list of Base64 encoded strings for the slideshow.
    """
    current_dir = os.path.dirname(__file__)
    images_data = []
    
    # Find all PNG and JPG files in the folder
    types = ('*.png', '*.jpg', '*.jpeg')
    files_grabbed = []
    for files in types:
        files_grabbed.extend(glob.glob(os.path.join(current_dir, files)))
    
    # Sort files alphabetically so you can control order (slide1, slide2, etc.)
    files_grabbed.sort()

    if not files_grabbed:
        print("[Theme Warning] No images found in loading folder!")
        return []

    # Encode all found images
    for image_path in files_grabbed:
        try:
            with open(image_path, "rb") as img_file:
                encoded = base64.b64encode(img_file.read()).decode('utf-8')
                ext = "png" if image_path.endswith(".png") else "jpg"
                images_data.append(f"data:image/{ext};base64,{encoded}")
        except Exception as e:
            print(f"[Theme Error] Could not load {image_path}: {e}")
            
    return images_data

# Get list of all images
SLIDES_DATA = get_all_images()

# Convert Python list to a JavaScript array string (safe for HTML injection)
JS_SLIDES_ARRAY = ", ".join([f"'{img}'" for img in SLIDES_DATA])

# --- PROFESSIONAL SPLASH HTML ---
SPLASH_HTML = f"""
<!DOCTYPE html>
<html>
<head>
<style>
    /* --- CYBERPUNK THEME VARIABLES --- */
    :root {{
        --cyber-dark: #0B0F19;
        --cyber-gray: #1A2332;
        --cyber-blue: #0066FF;
        --cyber-cyan: #00F0FF;
        --cyber-black: #050507;
    }}

    body {{
        margin: 0;
        padding: 0;
        width: 100vw;
        height: 100vh;
        background-color: #121212; 
        display: flex;
        justify-content: center;
        align-items: center;
        overflow: hidden;
        user-select: none;
        cursor: wait;
        font-family: 'Segoe UI', 'Roboto', monospace;
    }}

    .splash-container {{
        position: relative;
        /* Fixed Aspect Ratio Container to match 2752x1536 */
        width: 900px;
        height: 502px;
        
        background-color: #1e1e1e;
        box-shadow: 0 40px 80px rgba(0,0,0,0.8);
        border: 1px solid #333;
        overflow: hidden; /* Ensures slides don't spill out */
    }}

    /* --- SLIDESHOW LAYER --- */
    .slide {{
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        opacity: 0;
        transition: opacity 1.5s ease-in-out; /* Smooth fade duration */
        z-index: 1; /* Behind text */
    }}

    .slide.active {{
        opacity: 1;
    }}

    /* --- TEXT LAYERS (On top of slides) --- */
    .dynamic-text-container {{
        position: absolute;
        /* Kept your previous coordinates */
        left: 5.0%; 
        top: 45.0%;
        width: 400px; 
        z-index: 10; /* Above slides */
        text-align: left;
    }}

    .status-line {{
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 11px; 
        color: #ffffff;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 400; 
        text-shadow: 0 1px 2px rgba(0,0,0,0.9); /* Stronger shadow for readability over photos */
    }}

    .version-tag {{
        position: absolute;
        bottom: 20px; 
        right: 25px;   
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 12px;
        color: #ffffff; 
        letter-spacing: 1px;
        opacity: 0.9;
        z-index: 10;
        text-shadow: 0 1px 2px rgba(0,0,0,0.9);
    }}

    /* Fade In Animation for container */
    @keyframes fadeIn {{
        from {{ opacity: 0; }}
        to {{ opacity: 1; }}
    }}
    .splash-container {{ animation: fadeIn 1.0s ease-out; }}

    /* --- CYBERPUNK UPDATE MODAL STYLES --- */
    .update-overlay {{
        position: absolute; 
        top: 0; left: 0; 
        width: 100%; height: 100%;
        background: rgba(0, 0, 0, 0.85); 
        z-index: 999;
        display: none; 
        justify-content: center; 
        align-items: center;
        backdrop-filter: blur(8px); /* Blur effect matching your React modal */
    }}

    .update-box {{
        background-color: var(--cyber-dark);
        border: 1px solid var(--cyber-blue);
        box-shadow: 0 0 20px rgba(0, 102, 255, 0.3);
        padding: 40px; 
        text-align: center;
        border-radius: 24px;
        width: 450px;
        display: flex;
        flex-direction: column;
        gap: 15px;
        animation: popIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }}

    @keyframes popIn {{
        from {{ transform: scale(0.95); opacity: 0; }}
        to {{ transform: scale(1); opacity: 1; }}
    }}

    .update-box h2 {{ 
        color: #ffffff; 
        margin: 0; 
        font-size: 26px;
        font-weight: 900; 
        text-transform: uppercase;
        letter-spacing: -0.5px;
    }}
    
    .update-box h2 span {{
        color: var(--cyber-blue);
    }}

    .update-box p {{ 
        color: #9ca3af; 
        font-size: 14px; 
        margin: 0; 
        margin-bottom: 10px; 
    }}

    .update-buttons {{
        display: flex;
        gap: 12px;
        margin-top: 10px;
    }}

    .btn-cyber {{
        flex: 1;
        padding: 14px; 
        border-radius: 12px;
        font-weight: bold; 
        text-transform: uppercase;
        letter-spacing: 1px;
        font-size: 14px;
        cursor: pointer; 
        transition: all 0.2s;
    }}

    .btn-primary {{ 
        background-color: var(--cyber-blue); 
        color: white; 
        border: none;
        box-shadow: 0 0 10px rgba(0, 102, 255, 0.4);
    }}

    .btn-primary:hover {{ 
        filter: brightness(1.1);
        transform: scale(1.02);
    }}
    
    .btn-primary:active {{
        transform: scale(0.98);
    }}

    .btn-secondary {{ 
        background-color: transparent; 
        color: #d1d5db; 
        border: 1px solid #4b5563;
    }}

    .btn-secondary:hover {{ 
        background-color: #1f2937; 
    }}

    /* --- NEW PROGRESS BAR STYLES --- */
    .progress-container {{
        display: none;
        margin-top: 15px;
        width: 100%;
        background: #1a2332;
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid var(--cyber-blue);
    }}

    .progress-bar {{
        width: 0%;
        height: 12px;
        background: var(--cyber-cyan);
        box-shadow: 0 0 10px var(--cyber-cyan);
        transition: width 0.2s ease;
    }}

    .downloading-text {{ 
        color: var(--cyber-cyan); 
        display: none; 
        margin-top: 10px; 
        font-family: 'Consolas', monospace; 
        font-size: 16px; 
        font-weight: bold; 
        text-transform: uppercase;
        letter-spacing: 2px;
        animation: pulse 1.5s infinite;
    }}

    @keyframes pulse {{
        0%, 100% {{ opacity: 1; }}
        50% {{ opacity: 0.5; }}
    }}

</style>
</head>
<body>

    <div class="splash-container">
        <div id="slides-wrapper">
            </div>

        <div class="dynamic-text-container">
            <div id="status-text" class="status-line">INITIALIZING...</div>
        </div>

        <div class="version-tag">v{APP_VERSION}</div>

        <div id="update-modal" class="update-overlay">
            <div class="update-box">
                <h2>System <span id="update-ver">Update</span></h2>
                <p>A new version of GarmentQC AI Pro is available. Would you like to install it now?</p>
                
                <div id="update-buttons" class="update-buttons">
                    <button class="btn-cyber btn-secondary" onclick="sendUpdateChoice(false)">Skip for Now</button>
                    <button class="btn-cyber btn-primary" onclick="sendUpdateChoice(true)">Update Now</button>
                </div>

                <div id="progress-container" class="progress-container">
                    <div id="progress-bar" class="progress-bar"></div>
                </div>
                <div id="download-status" class="downloading-text">DOWNLOADING DATA... 0%</div>
            </div>
        </div>
    </div>

    <script>
        // --- 1. SLIDESHOW LOGIC ---
        // Array of Base64 images injected from Python
        const slidesData = [{JS_SLIDES_ARRAY}];
        const wrapper = document.getElementById('slides-wrapper');
        
        if (slidesData.length > 0) {{
            // Create Divs for each slide
            slidesData.forEach((imgSrc, index) => {{
                let div = document.createElement('div');
                div.className = 'slide';
                if (index === 0) div.classList.add('active'); // Show first immediately
                div.style.backgroundImage = "url('" + imgSrc + "')";
                wrapper.appendChild(div);
            }});

            // Start Cycle if more than 1 image
            if (slidesData.length > 1) {{
                let currentSlide = 0;
                const slides = document.querySelectorAll('.slide');
                
                setInterval(() => {{
                    slides[currentSlide].classList.remove('active');
                    currentSlide = (currentSlide + 1) % slides.length;
                    slides[currentSlide].classList.add('active');
                }}, 3000); // Change image every 3 seconds
            }}
        }} else {{
            // Fallback if no images found
            wrapper.style.backgroundColor = '#1e1e1e';
        }}

        // --- 2. LOADING TEXT LOGIC ---
        const messages = [
            "Initializing System...",
            "Loading Core Modules...",
            "Calibrating Neural Network...",
            "Checking Hardware...",
            "Verifying License...",
            "Starting Server...",
            "Loading UI...",
            "Syncing Configuration...",
            "Preparing Models...",
            "Connecting to Database...",
            "Validating Assets...",
            "Optimizing Pipelines...",
            "Warming Cache...",
            "Scanning Devices...",
            "Applying Settings...",
            "Registering Services...",
            "Resolving Dependencies...",
            "Finalizing Startup...",
            "Ready..."
        ];

        const textElement = document.getElementById('status-text');
        let msgIndex = 0;

        setInterval(() => {{
            if (msgIndex < messages.length) {{
                textElement.innerText = messages[msgIndex];
                msgIndex++;
            }}
        }}, 700);

        // --- 3. UPDATE PROMPT LOGIC ---
        function showUpdatePrompt(version) {{
            // Strip any leading 'v' to avoid double 'vv' display
            const cleanVersion = version.replace(/^v+/i, '');
            document.getElementById('update-ver').innerText = 'v' + cleanVersion;
            
            // Show the modal container
            document.getElementById('update-modal').style.display = 'flex';
            
            // Pause the background text initialization
            document.getElementById('status-text').innerText = "WAITING FOR USER INPUT...";
        }}

        // THIS IS THE NEW FUNCTION CALLED BY PYTHON DURING DOWNLOAD
        function updateDownloadProgress(percent) {{
            document.getElementById('progress-bar').style.width = percent + '%';
            document.getElementById('download-status').innerText = 'DOWNLOADING DATA... ' + percent + '%';
            
            if (percent >= 100) {{
                document.getElementById('download-status').innerText = 'EXTRACTING & APPLYING...';
            }}
        }}

        function sendUpdateChoice(choice) {{
            if (choice) {{
                // Hide buttons, show downloading text and progress bar
                document.getElementById('update-buttons').style.display = 'none';
                document.getElementById('download-status').style.display = 'block';
                document.getElementById('progress-container').style.display = 'block';
                document.getElementById('status-text').innerText = "DOWNLOADING UPDATE...";
            }} else {{
                // Hide modal and resume normal loading visually
                document.getElementById('update-modal').style.display = 'none';
                document.getElementById('status-text').innerText = "RESUMING STARTUP...";
            }}
            
            // Send the user's click back to Python!
            if (window.pywebview && window.pywebview.api) {{
                window.pywebview.api.submit_update_choice(choice);
            }} else {{
                console.warn("[Theme] pywebview bridge not found!");
            }}
        }}
    </script>

</body>
</html>
"""