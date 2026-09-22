import webview
import requests
import os
import sys
import time
import tempfile
import threading
import subprocess  # <--- Added for reliable rebooting

# --- IMPORT THEMES ---
# Tries to import the professional themes from the 'loading' folder.
# If the folder is missing, it falls back to a simple text loading/offline screen.
try:
    from loading.splash_theme import SPLASH_HTML
    from loading.offline_theme import OFFLINE_HTML
except ImportError:
    print("[WARN] Could not find themes. Using fallback.")
    SPLASH_HTML = "<h1>Loading Application...</h1>"
    OFFLINE_HTML = "<h1>No Internet. <button onclick='location.reload()'>Retry</button></h1>"

# Global reference to the window so we can change its URL dynamically
main_window = None

# --- JAVASCRIPT BRIDGE API ---
# This class allows the HTML UI (Activator/Block Screen/Offline Screen) to call Python functions.
class AppApi:
    def __init__(self):
        self._activation_callback = None
        # Placeholder for the retry function used in license_guard
        self.submit_retry = None
        # --- ADDED: Update prompt event and result ---
        self.update_event = threading.Event()
        self.update_choice = False
        # --- ADDED: Target URL for the retry button ---
        self.target_url = None

    def set_activation_callback(self, func):
        """Allows activator.py to hook into this API dynamically."""
        self._activation_callback = func

    def submit_activation(self, factory_id, device_id, email):
        """Called from JavaScript when user clicks 'Activate'"""
        if self._activation_callback:
            print(f"[API] Received Activation Request: {factory_id}-{device_id}")
            return self._activation_callback(factory_id, device_id, email)
        return {"success": False, "message": "System not ready"}

    def submit_update_choice(self, choice):
        """Called from JavaScript when user clicks 'Update Now' or 'Skip for Now'."""
        self.update_choice = bool(choice)
        self.update_event.set()

    def retry_connection(self):
        """Called from the Offline UI to retry connecting to the cloud."""
        print("[API] Retrying internet connection...")
        if self.target_url and check_connection(self.target_url):
            print("[API] Connection successful! Loading app...")
            if main_window:
                main_window.load_url(self.target_url)
            return True
        return False

# Create a global instance so other modules can access it
global_api = AppApi()

def check_connection(url):
    """
    Checks if a URL is reachable (e.g., checking if the server has started or internet is working).
    """
    try:
        requests.get(url, timeout=2)
        return True
    except:
        return False

def on_closed():
    """
    Force kills the application processes when the window is closed.
    """
    print("[INFO] Window closed. Exiting application...")
    # Silence any noisy errors during forced exit
    try:
        sys.stderr = open(os.devnull, 'w')
    except:
        pass
    os._exit(0)

def launch_kiosk(host_url, local_port=8000, startup_callback=None):
    """
    Launches the application with a Professional Splash Screen workflow:
    1. Writes Splash HTML to a temp file.
    2. Shows Splash Screen immediately.
    3. Runs 'startup_callback' in the background.
    4. Waits for the local server (port 8000) to come online.
    5. Checks Internet: If Offline -> Loads the Custom Offline/Wi-Fi Setup UI.
    """
    global main_window
    
    # Store the target cloud URL in the API so the retry button knows where to go
    global_api.target_url = host_url 

    # --- CRITICAL FIX: Write Splash HTML to a temp file ---
    # WebView2 crashes if you pass a massive Base64 string directly.
    splash_file_path = os.path.join(tempfile.gettempdir(), "garment_qc_splash.html")
    try:
        with open(splash_file_path, "w", encoding="utf-8") as f:
            f.write(SPLASH_HTML)
        splash_url = f"file://{splash_file_path}"
    except Exception as e:
        print(f"[Launcher Error] Could not write splash file: {e}")
        # Fallback (risky for large images, but better than crashing immediately)
        splash_url = "data:text/html," + SPLASH_HTML

    def transition_logic():
        # -------------------------------------------------
        # PHASE 1: BACKGROUND TASKS
        # -------------------------------------------------
        if startup_callback:
            print("[Splash] Running background startup tasks...")
            # This runs the function passed from windows_test.py
            # NOTE: This triggers license_guard.validate(), which may use main_window to show Activation UI
            startup_callback()

        # -------------------------------------------------
        # PHASE 2: WAIT FOR LOCAL SERVER
        # -------------------------------------------------
        print("[Splash] Waiting for UI Server to be ready...")
        
        # We wait up to 30 seconds for the backend to start
        max_retries = 60 
        local_url = f"http://localhost:{local_port}"
        server_ready = False

        for i in range(max_retries):
            if check_connection(local_url):
                server_ready = True
                break
            time.sleep(0.5)

        if not server_ready:
            print("[Error] Server failed to start in time.")

        # -------------------------------------------------
        # PHASE 3: CHECK CLOUD CONNECTION
        # -------------------------------------------------
        final_url = local_url
        
        # If a cloud URL is provided (e.g. Vercel), check it
        if host_url and "localhost" not in host_url:
            print(f"[Launcher] Checking connection to cloud: {host_url}...")
            
            if check_connection(host_url):
                print(f"[Launcher] Online Mode: Loading {host_url}")
                final_url = host_url
            else:
                print(f"[Launcher] Offline! Cloud unreachable. Loading Offline Mode.")
                
                # --- Write the Offline HTML to a temp file and load it ---
                offline_file_path = os.path.join(tempfile.gettempdir(), "garment_qc_offline.html")
                try:
                    with open(offline_file_path, "w", encoding="utf-8") as f:
                        f.write(OFFLINE_HTML)
                    final_url = f"file://{offline_file_path}"
                except Exception as e:
                    print(f"[Launcher Error] Could not write offline file: {e}")
                    final_url = "data:text/html," + OFFLINE_HTML

        # -------------------------------------------------
        # PHASE 4: TRANSITION TO APP
        # -------------------------------------------------
        if main_window:
            print(f"[Launcher] Switching view to: {final_url}")
            
            # Optional: A small sleep to let the progress bar visually finish
            # This makes the transition feel smoother
            time.sleep(1.5) 
            
            # Load the actual application interface or offline screen
            main_window.load_url(final_url)

    # -------------------------------------------------
    # CREATE THE WINDOW
    # -------------------------------------------------
    # We use the file URL we created above.
    main_window = webview.create_window(
        title="GarmentQC AI Pro",
        url=splash_url,        # <-- USES FILE URL (Stable)
        width=1280,
        height=800,
        frameless=True,        # Removes title bar for professional look
        fullscreen=True,       # Kiosk mode
        easy_drag=False,       # Prevents user from dragging the window
        on_top=False,
        background_color='#121212', # Deep grey to match your splash theme
        js_api=global_api      # <-- ADDED: Enables Python-JS communication
    )
    
    # Start the logic thread and the main GUI loop
    webview.start(func=transition_logic)
    
    # Clean up when the loop ends
    on_closed()