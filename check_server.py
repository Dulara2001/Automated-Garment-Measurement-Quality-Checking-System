
import requests
import time
import sys

print("Checking server status...")
try:
    for i in range(10):
        try:
            r = requests.get("http://localhost:8000")
            if r.status_code == 200:
                print("Server is UP and serving index.html")
                print(f"Content length: {len(r.text)}")
                sys.exit(0)
        except requests.exceptions.ConnectionError:
            print(f"Waiting for server... ({i+1}/10)")
            time.sleep(1)
    print("Server failed to respond.")
except Exception as e:
    print(f"Error checking server: {e}")
