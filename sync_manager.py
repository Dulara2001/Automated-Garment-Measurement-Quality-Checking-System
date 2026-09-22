import os
import json
import time
import threading
import copy
import base64
import boto3
from pathlib import Path
from datetime import datetime
from supabase import create_client, Client

# NOTE: We do NOT use 'load_dotenv' here. 
# Environment variables are injected securely by 'windows_test.py' at boot 
# from the encrypted configuration.

class CloudSyncManager:
    """
    Manages direct synchronization with Supabase (Database) and Cloudflare R2 (Storage).
    
    Features:
    1. Direct DB Insert (Supabase)
    2. Direct Image Upload (R2/S3)
    3. Offline Support: Saves to local disk if internet is down.
    4. Background Retry: Automatically uploads saved files when internet returns.
    """
    def __init__(self, pending_dir="data/pending_uploads", retry_interval=60):
        self.pending_dir = Path(pending_dir)
        self.retry_interval = retry_interval
        self.running = True
        
        # Create directory for offline files if it doesn't exist
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        
        # --- Initialize Clients ---
        self.supabase: Client = None
        self.r2_client = None
        
        # Attempt init immediately (using env vars from windows_test)
        self._init_clients()

        # Start the background worker thread
        self.worker_thread = threading.Thread(target=self._retry_worker, daemon=True)
        self.worker_thread.start()
        print(f"[SyncManager] Initialized. Offline storage: {self.pending_dir.resolve()}")

    def _init_clients(self):
        """Initializes Supabase and R2 clients using injected Environment Variables."""
        try:
            # Initialize Supabase
            if not self.supabase:
                url = os.getenv("SUPABASE_URL")
                key = os.getenv("SUPABASE_KEY")
                if url and key:
                    self.supabase = create_client(url, key)

            # Initialize Cloudflare R2 (S3 Compatible)
            if not self.r2_client:
                self.r2_client = boto3.client(
                    's3',
                    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
                    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
                    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
                    region_name='auto'
                )
                self.bucket_name = os.getenv("R2_BUCKET_NAME")
                self.public_domain = os.getenv("R2_PUBLIC_DOMAIN")
                
        except Exception as e:
            # It's okay if this fails initially (e.g. offline); it will retry when upload is called
            print(f"[SyncManager] Client Init Warning: {e}")

    def upload_now(self, report_data):
        """
        Public method called by the main app.
        Attempts to sync report and images to cloud immediately.
        Runs in a separate thread to prevent UI freezing.
        """
        # Create a deep copy to ensure thread safety and avoid modifying original data
        data_snapshot = copy.deepcopy(report_data)
        
        # Run in a separate thread so it doesn't block the UI/Camera
        threading.Thread(target=self._process_upload, args=(data_snapshot,), daemon=True).start()

    def _process_upload(self, report):
        """Internal handler for the upload thread."""
        print(f"[Sync] Processing Report ID: {report.get('id', 'Unknown')}...")
        
        # Attempt immediate sync
        success = self._perform_full_sync(report)
        
        if not success:
            print(f"[Sync] Upload failed or offline. Saving to local disk...")
            self._save_pending_task(report)
        else:
            print(f"[Sync] Everything synced successfully!")

    def _perform_full_sync(self, report):
        """
        Executes the full sync logic:
        1. Insert into Supabase DB
        2. Upload Images to R2
        3. Link Images in DB
        """
        try:
            # Ensure clients are ready
            if not self.supabase or not self.r2_client:
                self._init_clients()
                if not self.supabase or not self.r2_client:
                    return False

            factory_id = os.getenv("FACTORY_ID", "UNKNOWN_FACTORY")
            factory_name = os.getenv("FACTORY_NAME", "FACTORY").replace(" ", "_")
            
            # --- Step 1: Insert into 'measurements' table ---
            measurement_record = {
                "factory_id": factory_id,
                "device_id": report.get("device_id", "UNKNOWN_DEVICE"),
                "production_line_id": report.get("line_id", "UNKNOWN_LINE"),
                # "line_name": report.get("line_name", "Unknown"),
                "client_ref_id": report.get("id", "UNKNOWN"),
                "garment_type": report.get("garment_type"),
                "style_name": report.get("style", ""),
                "detected_size": report.get("detected_size"),
                "confidence": report.get("confidence"),
                "pixels_per_cm": report.get("pixels_per_cm", 0),
                "qc_status": report.get("qc_status"),
                "measurement_data": report.get("measurements") # Stores full JSON array
            }
            # Execute Insert
            res = self.supabase.table("measurements").insert(measurement_record).execute()
            
            if not res.data:
                print("[Sync Error] Database insert returned no data.")
                return False
            
            # Get the ID generated by Supabase
            measurement_id = res.data[0]['id']

            # --- Step 2: Upload Images to R2 ---
            # Mapping report keys to database ENUM types
            image_map = [
                ('base_image', 'BASE'),
                ('detect_overlay', 'DETECT'),
                ('measure_overlay', 'MEASURE')
            ]
            
            image_records = []
            
            for field, img_type in image_map:
                b64_str = report.get(field)
                if b64_str:
                    url = self._upload_to_r2(b64_str, factory_name, measurement_id, img_type)
                    if url:
                        image_records.append({
                            "measurement_id": measurement_id,
                            "image_type": img_type,
                            "storage_url": url
                        })

            # --- Step 3: Link Images in 'measurement_images' table ---
            if image_records:
                self.supabase.table("measurement_images").insert(image_records).execute()
            
            return True

        except Exception as e:
            print(f"[Sync Error] Full sync failed: {e}")
            return False

    def _upload_to_r2(self, b64_string, factory_name, meas_id, img_type):
        """Helper to upload base64 string to R2 and return the public URL."""
        try:
            # Clean base64 header (e.g., "data:image/webp;base64,") if present
            if "," in b64_string:
                b64_string = b64_string.split(",")[1]
            
            file_data = base64.b64decode(b64_string)
            file_name = f"{factory_name}_{meas_id}_{img_type}.webp"
            
            # Structure: garment/FACTORY_NAME/filename.webp
            storage_path = f"garment/{factory_name}/{file_name}"

            self.r2_client.put_object(
                Bucket=self.bucket_name,
                Key=storage_path,
                Body=file_data,
                ContentType='image/webp'
            )
            
            return f"{self.public_domain}/{storage_path}"
        except Exception as e:
            print(f"[R2 Error] Upload failed for {img_type}: {e}")
            return None

    def _save_pending_task(self, data):
        """Saves the report data to a JSON file in the pending directory."""
        task_id = f"task_{int(time.time() * 1000)}"
        task_file = self.pending_dir / f"{task_id}.json"
        try:
            with open(task_file, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"[Offline] Task saved: {task_file.name}")
        except Exception as e:
            print(f"[Sync] Critical Error: Could not save offline task: {e}")

    def _retry_worker(self):
        """Background thread that checks for offline files and tries to sync them."""
        while self.running:
            try:
                # Find all .json files in the pending directory
                pending_files = list(self.pending_dir.glob("*.json"))
                
                if pending_files:
                    print(f"[Worker] Found {len(pending_files)} pending tasks. Attempting sync...")
                    
                    # Process oldest first
                    for p_file in sorted(pending_files):
                        try:
                            with open(p_file, 'r') as f:
                                task_data = json.load(f)
                            
                            # Attempt sync
                            if self._perform_full_sync(task_data):
                                print(f"[Worker] Sync Success! Deleting {p_file.name}")
                                os.remove(p_file)
                            else:
                                # If sync fails, stop processing to save bandwidth/resources
                                # and wait for the next interval
                                break
                                
                        except json.JSONDecodeError:
                            print(f"[Worker] Corrupt file found: {p_file.name}. Deleting.")
                            os.remove(p_file)
                        except Exception as e:
                            print(f"[Worker] Error processing {p_file.name}: {e}")
                            
            except Exception as main_e:
                print(f"[Worker Error] Loop exception: {main_e}")
            
            # Wait before checking again
            time.sleep(self.retry_interval)

    def save_local_standards(self, standards_json_str, target_path):
        """
        Updates local size standards from UI/API.
        Required for compatibility with endpoints_server.py.
        """
        try:
            if not standards_json_str: return
            data = json.loads(standards_json_str)
            Path(target_path).parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"[Sync] Local standards updated at {target_path}")
        except Exception as e:
            print(f"[Sync] Error saving local standards: {e}")

    def stop(self):
        """Stops the background worker thread safely."""
        self.running = False
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2)