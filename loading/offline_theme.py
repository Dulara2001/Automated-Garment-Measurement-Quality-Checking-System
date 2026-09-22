"""
GarmentQC AI - Offline & Wi-Fi Setup Theme
Location: loading/offline_theme.py
"""

OFFLINE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connection Error</title>
    <style>
        /* --- CYBERPUNK THEME VARIABLES --- */
        :root {
            --cyber-dark: #0B0F19;
            --cyber-gray: #1A2332;
            --cyber-blue: #0066FF;
            --cyber-cyan: #00F0FF;
            --cyber-black: #050507;
        }

        body {
            margin: 0;
            padding: 0;
            width: 100vw;
            height: 100vh;
            background-color: var(--cyber-black);
            color: white;
            font-family: 'Segoe UI', 'Roboto', monospace;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            user-select: none;
        }

        .container {
            background-color: var(--cyber-dark);
            border: 1px solid var(--cyber-blue);
            border-radius: 16px;
            padding: 40px;
            width: 650px;
            max-height: 85vh;
            box-shadow: 0 0 30px rgba(0, 102, 255, 0.2);
            text-align: center;
            display: flex;
            flex-direction: column;
        }

        h1 { 
            margin-top: 0; 
            color: #ff4444; 
            font-size: 28px; 
            text-transform: uppercase; 
            letter-spacing: 2px;
            text-shadow: 0 0 10px rgba(255, 68, 68, 0.4);
        }

        p { 
            color: #9ca3af; 
            margin-bottom: 30px; 
            font-size: 14px;
        }
        
        .btn-group { 
            display: flex; 
            gap: 15px; 
            justify-content: center; 
            margin-bottom: 20px; 
        }

        button {
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 1px;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
            font-family: inherit;
        }

        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-primary { 
            background-color: var(--cyber-blue); 
            color: white; 
            box-shadow: 0 0 10px rgba(0, 102, 255, 0.4);
        }

        .btn-primary:hover:not(:disabled) { 
            filter: brightness(1.2); 
            transform: translateY(-1px);
        }

        .btn-primary:active:not(:disabled) {
            transform: translateY(1px);
        }

        .btn-secondary { 
            background-color: transparent; 
            border: 1px solid #4b5563; 
            color: #d1d5db; 
        }

        .btn-secondary:hover:not(:disabled) { 
            background-color: #1f2937; 
            color: white;
        }

        /* --- WI-FI SECTION STYLES --- */
        #wifi-section { 
            display: none; 
            text-align: left; 
            border-top: 1px solid #333; 
            padding-top: 20px; 
            flex-grow: 1;
            overflow-y: auto;
        }

        #wifi-section::-webkit-scrollbar { width: 8px; }
        #wifi-section::-webkit-scrollbar-track { background: #111; border-radius: 4px; }
        #wifi-section::-webkit-scrollbar-thumb { background: #333; border-radius: 4px; }
        #wifi-section::-webkit-scrollbar-thumb:hover { background: var(--cyber-blue); }

        .wifi-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }

        .wifi-header h3 {
            margin: 0;
            color: white;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .header-buttons {
            display: flex;
            gap: 10px;
        }

        .network-item {
            background: rgba(255, 255, 255, 0.03);
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            border: 1px solid transparent;
            transition: all 0.2s;
        }

        .network-item:hover { 
            border-color: var(--cyber-blue); 
            background: rgba(0, 102, 255, 0.05);
        }

        .network-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .network-name { font-weight: bold; font-size: 16px; }
        .network-meta { font-size: 12px; color: #888; }

        .status-badge {
            font-size: 10px; padding: 3px 6px; border-radius: 4px; font-weight: bold; letter-spacing: 1px;
        }
        .status-connected { background: rgba(0, 255, 0, 0.1); color: #00ff00; border: 1px solid rgba(0, 255, 0, 0.3); }
        .status-open { background: rgba(255, 170, 0, 0.1); color: #ffaa00; border: 1px solid rgba(255, 170, 0, 0.3); }

        .password-box { 
            display: none; 
            margin-top: -5px; 
            margin-bottom: 15px;
            padding: 15px;
            background: #111;
            border-radius: 0 0 8px 8px;
            border: 1px solid #333;
            border-top: none;
            gap: 10px; 
        }

        input[type="password"] {
            flex-grow: 1; padding: 10px 15px; border-radius: 6px; border: 1px solid #444;
            background: #000; color: white; outline: none; font-family: inherit;
        }
        input[type="password"]:focus { border-color: var(--cyber-blue); }

        #status-message {
            margin-top: 15px; font-size: 13px; color: var(--cyber-cyan); min-height: 20px;
        }
    </style>
</head>
<body>

<div class="container">
    <h1>System Offline</h1>
    <p>The application cannot reach the cloud server. Please check your internet connection and retry, or configure your local Wi-Fi below.</p>
    
    <div class="btn-group">
        <button class="btn-primary" onclick="retryConnection()" id="retry-btn">Retry Connection</button>
        <button class="btn-secondary" onclick="toggleWifiSection()" id="wifi-toggle-btn">Wi-Fi Settings</button>
    </div>

    <div id="status-message"></div>

    <div id="wifi-section">
        <div class="wifi-header">
            <h3>Available Networks</h3>
            <div class="header-buttons">
                <button id="adapter-btn" class="btn-secondary" style="padding: 6px 12px; font-size: 12px; color: gray;" onclick="toggleAdapterPower()">Detecting...</button>
                <button id="refresh-btn" class="btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="scanWifi()">Refresh Scan</button>
            </div>
        </div>
        <div id="network-list">Initializing network scanner...</div>
    </div>
</div>

<script>
    const API_BASE = "http://localhost:8000";
    let isAdapterOn = true; // Tracks PC Hardware state

    // --- INTERACT WITH PYTHON APP (pywebview bridge) ---
    async function retryConnection() {
        const btn = document.getElementById('retry-btn');
        const msg = document.getElementById('status-message');
        
        btn.innerText = "Checking...";
        msg.innerText = "Attempting to reach cloud server...";
        msg.style.color = "var(--cyber-cyan)";
        
        if (window.pywebview && window.pywebview.api) {
            try {
                const isOnline = await window.pywebview.api.retry_connection();
                if (!isOnline) {
                    btn.innerText = "Still Offline - Retry";
                    btn.style.backgroundColor = "#ff4444";
                    msg.innerText = "Cloud server is still unreachable. Please check your Wi-Fi.";
                    msg.style.color = "#ff4444";
                    setTimeout(() => { btn.style.backgroundColor = "var(--cyber-blue)"; }, 2000);
                } else {
                    msg.innerText = "Connection restored! Loading app...";
                    msg.style.color = "#00ff00";
                }
            } catch (e) {
                msg.innerText = "Error communicating with system launcher.";
                msg.style.color = "#ff4444";
                btn.innerText = "Retry Connection";
            }
        } else {
            msg.innerText = "System bridge not ready. Please wait a moment and try again.";
            msg.style.color = "#ffaa00";
            btn.innerText = "Retry Connection";
        }
    }

    // --- WI-FI UI TOGGLE ---
    function toggleWifiSection() {
        const sec = document.getElementById('wifi-section');
        const btn = document.getElementById('wifi-toggle-btn');
        
        if (sec.style.display === 'none' || sec.style.display === '') {
            sec.style.display = 'block';
            btn.style.backgroundColor = '#1f2937';
            btn.style.color = 'white';
            scanWifi(); // Triggers scan when opened
        } else {
            sec.style.display = 'none';
            btn.style.backgroundColor = 'transparent';
            btn.style.color = '#d1d5db';
            document.getElementById('status-message').innerText = "";
        }
    }

    // --- HARDWARE POWER TOGGLE (ON/OFF) ---
    async function toggleAdapterPower() {
        const btn = document.getElementById('adapter-btn');
        const list = document.getElementById('network-list');
        const msg = document.getElementById('status-message');
        const refreshBtn = document.getElementById('refresh-btn');
        
        const newState = !isAdapterOn; // Flip the state
        
        btn.innerText = newState ? "Enabling..." : "Disabling...";
        btn.disabled = true;
        refreshBtn.disabled = true;
        msg.innerText = `Turning Wi-Fi Adapter ${newState ? 'ON' : 'OFF'}...`;

        try {
            const res = await fetch(`${API_BASE}/api/wifi/toggle`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ state: newState })
            });
            const data = await res.json();
            
            if (data.success) {
                isAdapterOn = newState;
                updateAdapterButtonStyle();
                
                if (newState) {
                    msg.innerText = "Adapter enabled. Booting up scan...";
                    list.innerHTML = "<div style='text-align: center; padding: 20px; color: #00ff00;'>Hardware ON. Refreshing networks...</div>";
                    setTimeout(scanWifi, 3500); // Wait 3.5s for Windows hardware to wake up before scanning
                } else {
                    msg.innerText = "Adapter disabled.";
                    list.innerHTML = "<div style='text-align: center; padding: 20px; color: #ff4444;'>Wi-Fi Adapter is turned OFF. Click 'Adapter: OFF' to turn it back on.</div>";
                }
            } else {
                alert(data.message || "Toggle failed. Please ensure the app is running as Administrator.");
                updateAdapterButtonStyle(); // Revert visual state
            }
        } catch (e) {
            alert("Error communicating with Wi-Fi hardware service.");
            updateAdapterButtonStyle(); // Revert visual state
        }
        
        btn.disabled = false;
        refreshBtn.disabled = false;
    }

    function updateAdapterButtonStyle() {
        const btn = document.getElementById('adapter-btn');
        if (isAdapterOn) {
            btn.innerText = "Adapter: ON";
            btn.style.borderColor = "#00ff00";
            btn.style.color = "#00ff00";
        } else {
            btn.innerText = "Adapter: OFF";
            btn.style.borderColor = "#ff4444";
            btn.style.color = "#ff4444";
        }
    }

    // --- SCAN WI-FI ---
    async function scanWifi() {
        const list = document.getElementById('network-list');
        const msg = document.getElementById('status-message');
        const refreshBtn = document.getElementById('refresh-btn');
        
        refreshBtn.disabled = true;
        list.innerHTML = "<div style='text-align: center; padding: 20px; color: #888;'>Scanning for networks...</div>";
        msg.innerText = "Scanning nearby Wi-Fi networks...";
        msg.style.color = "var(--cyber-cyan)";

        try {
            const res = await fetch(`${API_BASE}/api/wifi/scan`);
            const data = await res.json();
            
            if (data.success) {
                // Update adapter hardware state based on response
                if (data.current && data.current.adapter_enabled !== undefined) {
                    isAdapterOn = data.current.adapter_enabled;
                    updateAdapterButtonStyle();
                }

                if (!isAdapterOn) {
                    list.innerHTML = "<div style='text-align: center; padding: 20px; color: #ff4444;'>Wi-Fi Adapter is turned OFF. Click 'Adapter: OFF' to turn it back on.</div>";
                    msg.innerText = "Hardware disabled.";
                    refreshBtn.disabled = false;
                    return;
                }

                msg.innerText = "Scan complete.";
                
                if (data.networks && data.networks.length > 0) {
                    list.innerHTML = ""; 
                    data.networks.forEach((net, index) => {
                        const isConnected = data.current && data.current.ssid === net.ssid && data.current.connected;
                        const isOpen = !net.secure;
                        
                        let itemHtml = `
                            <div class="network-item" onclick="togglePasswordBox('${net.ssid}', ${index}, ${isOpen})">
                                <div class="network-info">
                                    <span class="network-name">${net.ssid}</span>
                                    <span class="network-meta">Signal: ${net.signal}% | ${net.auth || 'Unknown Security'}</span>
                                </div>
                                <div>
                                    ${isOpen ? '<span class="status-badge status-open">OPEN</span>' : ''}
                                    ${isConnected ? '<span class="status-badge status-connected">CONNECTED</span>' : ''}
                                </div>
                            </div>
                            <div id="pwd-box-${index}" class="password-box">
                                <input type="password" id="input-${index}" placeholder="Enter Network Password" onkeydown="if(event.key === 'Enter') connectWifi('${net.ssid}', ${index})">
                                <button class="btn-primary" style="padding: 10px 20px; font-size: 12px;" onclick="connectWifi('${net.ssid}', ${index})" id="btn-connect-${index}">Connect</button>
                            </div>
                        `;
                        list.innerHTML += itemHtml;
                    });
                } else {
                    list.innerHTML = "<div style='text-align: center; padding: 20px; color: #ffaa00;'>No networks found.</div>";
                }
            } else {
                list.innerHTML = `<div style='text-align: center; padding: 20px; color: #ff4444;'>Scan failed: ${data.error || 'Unknown error'}</div>`;
                msg.innerText = "Scan failed.";
            }
        } catch (e) {
            list.innerHTML = "<div style='text-align: center; padding: 20px; color: #ff4444;'>Cannot reach local hardware service. Is the background server running?</div>";
            msg.innerText = "Hardware communication error.";
            msg.style.color = "#ff4444";
        }
        refreshBtn.disabled = false;
    }

    function togglePasswordBox(ssid, index, isOpen) {
        document.querySelectorAll('.password-box').forEach(el => el.style.display = 'none');
        
        if (isOpen) {
            document.getElementById('status-message').innerText = `Attempting open connection to ${ssid}...`;
            connectWifi(ssid, index, true);
            return;
        }
        
        const pwdBox = document.getElementById(`pwd-box-${index}`);
        pwdBox.style.display = 'flex';
        setTimeout(() => { document.getElementById(`input-${index}`).focus(); }, 100);
    }

    async function connectWifi(ssid, index, isOpen = false) {
        const msg = document.getElementById('status-message');
        const connectBtn = document.getElementById(`btn-connect-${index}`);
        let pwd = "";
        
        if (!isOpen) {
            pwd = document.getElementById(`input-${index}`).value;
            if (connectBtn) {
                connectBtn.innerText = "Connecting...";
                connectBtn.disabled = true;
            }
        }

        msg.innerText = `Connecting to ${ssid}...`;
        msg.style.color = "var(--cyber-cyan)";
        
        try {
            const res = await fetch(`${API_BASE}/api/wifi/connect`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ssid: ssid, password: pwd })
            });
            const result = await res.json();
            
            if (result.success) {
                msg.innerText = `Successfully connected to ${ssid}! Click 'Retry Connection' to launch the app.`;
                msg.style.color = "#00ff00";
                
                if (!isOpen) {
                    document.getElementById(`pwd-box-${index}`).style.display = 'none';
                    document.getElementById(`input-${index}`).value = "";
                }
                setTimeout(scanWifi, 2000); // Give it a moment to stabilize before rescanning
            } else {
                msg.innerText = `Connection failed: ${result.message}`;
                msg.style.color = "#ff4444";
                if (connectBtn) {
                    connectBtn.innerText = "Connect";
                    connectBtn.disabled = false;
                }
            }
        } catch (e) {
            msg.innerText = "Failed to send connection request. Hardware error.";
            msg.style.color = "#ff4444";
            if (connectBtn) {
                connectBtn.innerText = "Connect";
                connectBtn.disabled = false;
            }
        }
    }
</script>
</body>
</html>
"""