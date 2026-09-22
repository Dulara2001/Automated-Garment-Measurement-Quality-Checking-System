import subprocess
import os
import re
import time
import tempfile
import ctypes
import sys

class WifiManager:
    def __init__(self):
        """
        Initialize WiFi Manager with auto-detected interface name.
        CRITICAL: This app MUST run as Administrator for enable/disable to work.
        """
        self.interface = self._detect_wifi_interface()
        self._check_admin_privileges()
    
    def _check_admin_privileges(self):
        """Check if running as Administrator (required for toggle operations)"""
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
            if not is_admin:
                print("[WARNING] Not running as Administrator. Toggle WiFi will fail.")
                print("[WARNING] Right-click .exe → Run as Administrator")
            return is_admin
        except:
            return False
    
    def _detect_wifi_interface(self):
        """
        Auto-detect the WiFi interface name instead of hardcoding.
        Common names: "Wi-Fi", "Wireless Network Connection", "WLAN"
        """
        try:
            result = subprocess.check_output(
                'netsh interface show interface', 
                shell=True, 
                stderr=subprocess.STDOUT
            )
            output = result.decode('utf-8', errors='ignore')
            
            # Look for wireless interface
            for line in output.split('\n'):
                if 'wireless' in line.lower() or 'wi-fi' in line.lower():
                    # Extract interface name (last column)
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        return parts[-1]
            
            # Fallback to common names
            for name in ["Wi-Fi", "WLAN", "Wireless Network Connection"]:
                test = subprocess.run(
                    f'netsh interface show interface "{name}"',
                    shell=True,
                    capture_output=True
                )
                if test.returncode == 0:
                    return name
                    
        except Exception as e:
            print(f"[WiFi] Interface detection failed: {e}")
        
        # Default fallback
        return "Wi-Fi"

    def _run_command(self, command):
        """Execute Windows command and return output"""
        try:
            result = subprocess.check_output(
                command, 
                shell=True, 
                stderr=subprocess.STDOUT,
                timeout=10
            )
            return result.decode('utf-8', errors='ignore').strip()
        except subprocess.CalledProcessError as e:
            print(f"[WiFi] Command failed: {command}")
            print(f"[WiFi] Error: {e.output.decode('utf-8', errors='ignore')}")
            return None
        except subprocess.TimeoutExpired:
            print(f"[WiFi] Command timeout: {command}")
            return None

    def get_current_status(self):
        """
        Returns comprehensive WiFi status including:
        - Adapter power state (enabled/disabled)
        - Connection status (connected/disconnected)
        - Current SSID if connected
        - Signal strength
        """
        # First check if adapter is enabled
        interface_status = self._run_command(
            f'netsh interface show interface "{self.interface}"'
        )
        
        adapter_enabled = True
        if interface_status:
            if "disabled" in interface_status.lower():
                adapter_enabled = False
                return {
                    "adapter_enabled": False,
                    "connected": False,
                    "ssid": "",
                    "signal": 0,
                    "state": "ADAPTER_DISABLED"
                }
        
        # Check connection details
        output = self._run_command('netsh wlan show interfaces')
        if not output:
            return {
                "adapter_enabled": adapter_enabled,
                "connected": False,
                "ssid": "",
                "signal": 0,
                "state": "DISCONNECTED"
            }
        
        ssid_match = re.search(r'^\s*SSID\s*:\s*(.*)$', output, re.MULTILINE)
        state_match = re.search(r'^\s*State\s*:\s*(.*)$', output, re.MULTILINE)
        signal_match = re.search(r'^\s*Signal\s*:\s*(.*)$', output, re.MULTILINE)
        
        connected = False
        ssid = ""
        signal = 0
        
        if state_match:
            state_str = state_match.group(1).strip().lower()
            connected = "connected" in state_str and "disconnected" not in state_str
        
        if ssid_match and connected:
            ssid = ssid_match.group(1).strip()
        
        if signal_match:
            signal_str = signal_match.group(1).strip().replace('%', '')
            try:
                signal = int(signal_str)
            except:
                pass
        
        return {
            "adapter_enabled": adapter_enabled,
            "connected": connected,
            "ssid": ssid,
            "signal": signal,
            "state": "CONNECTED" if connected else "DISCONNECTED"
        }

    def scan_networks(self):
        """
        Scans for available WiFi networks.
        Returns list sorted by signal strength.
        """
        # First check if adapter is enabled
        status = self.get_current_status()
        if not status.get("adapter_enabled", True):
            print("[WiFi] Cannot scan - adapter is disabled")
            return []
        
        output = self._run_command('netsh wlan show networks mode=bssid')
        if not output:
            return []

        networks = []
        current_ssid = None
        current_auth = None
        
        for line in output.split('\n'):
            line = line.strip()
            
            # Extract SSID
            if line.startswith("SSID"):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    current_ssid = parts[1].strip()
            
            # Extract security type
            elif line.startswith("Authentication"):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    current_auth = parts[1].strip()
            
            # Extract signal strength
            elif line.startswith("Signal") and current_ssid:
                parts = line.split(":", 1)
                if len(parts) > 1:
                    signal_str = parts[1].strip().replace("%", "")
                    try:
                        signal = int(signal_str)
                    except:
                        signal = 0
                    
                    # Determine if network is secure
                    is_secure = current_auth and "open" not in current_auth.lower()
                    
                    # Avoid duplicates and empty SSIDs
                    if current_ssid and not any(n['ssid'] == current_ssid for n in networks):
                        networks.append({
                            "ssid": current_ssid,
                            "signal": signal,
                            "secure": is_secure,
                            "auth": current_auth or "Unknown"
                        })
                    
                    current_ssid = None
                    current_auth = None
        
        # Sort by signal strength (strongest first)
        return sorted(networks, key=lambda x: x['signal'], reverse=True)

    def connect_to_network(self, ssid, password=""):
        """
        Connect to a WiFi network with given credentials.
        Supports both secured (WPA2) and open networks.
        """
        # Check if already connected to this network
        status = self.get_current_status()
        if status["connected"] and status["ssid"] == ssid:
            return {
                "success": True,
                "message": f"Already connected to {ssid}"
            }
        
        # Determine if network is open (no password required)
        is_open = password == ""
        
        # Create appropriate profile XML
        if is_open:
            profile_xml = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{ssid}</name>
    <SSIDConfig>
        <SSID>
            <name>{ssid}</name>
        </SSID>
    </SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>auto</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>open</authentication>
                <encryption>none</encryption>
                <useOneX>false</useOneX>
            </authEncryption>
        </security>
    </MSM>
</WLANProfile>"""
        else:
            # WPA2-PSK with AES (most common)
            profile_xml = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{ssid}</name>
    <SSIDConfig>
        <SSID>
            <name>{ssid}</name>
        </SSID>
    </SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>auto</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>WPA2PSK</authentication>
                <encryption>AES</encryption>
                <useOneX>false</useOneX>
            </authEncryption>
            <sharedKey>
                <keyType>passPhrase</keyType>
                <protected>false</protected>
                <keyMaterial>{password}</keyMaterial>
            </sharedKey>
        </security>
    </MSM>
</WLANProfile>"""

        try:
            # Save profile to temp file
            fd, path = tempfile.mkstemp(suffix=".xml", text=True)
            with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
                tmp.write(profile_xml)

            # Add profile
            add_result = self._run_command(f'netsh wlan add profile filename="{path}" user=all')
            
            # Delete existing connection attempt to avoid conflicts
            self._run_command(f'netsh wlan disconnect')
            time.sleep(1)
            
            # Connect to network
            connect_result = self._run_command(f'netsh wlan connect name="{ssid}"')
            
            # Cleanup temp file
            try:
                os.remove(path)
            except:
                pass
            
            # Verify connection (wait up to 10 seconds)
            for i in range(10):
                time.sleep(1)
                status = self.get_current_status()
                if status["connected"] and status["ssid"] == ssid:
                    return {
                        "success": True,
                        "message": f"Connected to {ssid}"
                    }
            
            # Connection timeout
            return {
                "success": False,
                "message": "Connection timeout. Check password or signal strength."
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection error: {str(e)}"
            }

    def disconnect(self):
        """
        Disconnect from current WiFi network.
        """
        try:
            result = self._run_command('netsh wlan disconnect')
            time.sleep(1)  # Give Windows time to process
            
            status = self.get_current_status()
            if not status["connected"]:
                return {
                    "success": True,
                    "message": "Disconnected successfully"
                }
            else:
                return {
                    "success": False,
                    "message": "Disconnect command sent but still connected"
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Disconnect failed: {str(e)}"
            }

    def toggle_wifi(self, enable):
        """
        Enable or disable the WiFi adapter.
        REQUIRES ADMINISTRATOR PRIVILEGES.
        
        Args:
            enable (bool): True to enable, False to disable
        
        Returns:
            dict: Success status and message (for compatibility with old code)
            bool: True if command was sent (for compatibility with old code)
        """
        # Check admin privileges
        if not self._check_admin_privileges():
            print("[WiFi] Administrator privileges required for toggle")
            return False
        
        action = "enable" if enable else "disable"
        
        try:
            # Method 1: Use netsh interface
            cmd = f'netsh interface set interface "{self.interface}" admin={action}'
            print(f"[WiFi] Executing: {cmd}")
            
            result = self._run_command(cmd)
            
            # Wait for Windows to process the change
            time.sleep(3)
            
            # Verify the change
            status = self.get_current_status()
            
            if enable:
                if status.get("adapter_enabled", False):
                    return True
                else:
                    # Try alternative method
                    return self._toggle_wifi_alternative(enable)
            else:
                if not status.get("adapter_enabled", True):
                    return True
                else:
                    # Try alternative method
                    return self._toggle_wifi_alternative(enable)
                    
        except Exception as e:
            print(f"[WiFi] Toggle error: {e}")
            return False
    
    def _toggle_wifi_alternative(self, enable):
        """
        Alternative method using wmic (Windows Management Instrumentation)
        """
        try:
            if enable:
                cmd = f'wmic path win32_networkadapter where "NetConnectionID=\'{self.interface}\'" call enable'
            else:
                cmd = f'wmic path win32_networkadapter where "NetConnectionID=\'{self.interface}\'" call disable'
            
            result = self._run_command(cmd)
            time.sleep(2)
            
            status = self.get_current_status()
            expected_state = enable
            actual_state = status.get("adapter_enabled", False)
            
            return actual_state == expected_state
        except Exception as e:
            print(f"[WiFi] Alternative toggle failed: {e}")
            return False

    def forget_network(self, ssid):
        """
        Remove a saved WiFi profile.
        """
        try:
            cmd = f'netsh wlan delete profile name="{ssid}"'
            result = self._run_command(cmd)
            return {
                "success": True,
                "message": f"Forgot network: {ssid}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to forget network: {str(e)}"
            }

    def get_saved_profiles(self):
        """
        Get list of saved WiFi profiles.
        """
        try:
            output = self._run_command('netsh wlan show profiles')
            if not output:
                return []
            
            profiles = []
            for line in output.split('\n'):
                if 'All User Profile' in line or 'User Profile' in line:
                    parts = line.split(':', 1)
                    if len(parts) > 1:
                        profile_name = parts[1].strip()
                        if profile_name:
                            profiles.append(profile_name)
            
            return profiles
        except:
            return []