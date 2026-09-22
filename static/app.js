// --- CONFIGURATION ---
const API_BASE = 'http://localhost:8000'; 

document.addEventListener('DOMContentLoaded', async () => {

    // --- UI ELEMENTS ---
    const video = document.getElementById('videoFeed');
    const resImg = document.getElementById('resultImage');
    const fileIn = document.getElementById('fileInput');
    const ppcmIn = document.getElementById('ppcm');
    const typeIn = document.getElementById('garmentType');
    const styleSelect = document.getElementById('styleSelect');
    const statusBadge = document.getElementById('statusBadge');
    
    // QC Modal Elements
    const qcModal = document.getElementById('qcModal');
    const qcTitle = document.getElementById('qcTitle');
    const qcMessage = document.getElementById('qcMessage');
    const qcList = document.getElementById('qcFailureList');
    
    let isLive = false;
    let garmentConfig = null;
    let lastResultData = null; 

    // --- 1. INITIALIZATION & CONFIG ---

    async function init() {
        try {
            // Load Calibration
            const res = await fetch(`${API_BASE}/api/calibration`);
            const data = await res.json();
            if (data.pixels_per_cm && data.pixels_per_cm > 0) {
                ppcmIn.value = data.pixels_per_cm;
            }
        } catch (e) { console.log('No saved calibration'); }

        try {
            // Load Garment Config
            const res = await fetch(`${API_BASE}/api/config`);
            garmentConfig = await res.json();
            updateCsvTemplateHelp(); 
        } catch (e) { console.error("Failed to load config", e); }
        
        // Start Camera
        startVirtualCamera();
    }
    init();

    // --- 2. CAMERA CONNECTION ---
    // Uses the backend's own MJPEG stream (same one the real kiosk screen
    // uses) instead of the browser's getUserMedia, so it always shows
    // whichever physical camera the backend picked and needs no camera
    // permission prompt or extra virtual-camera driver.
    function startVirtualCamera() {
        video.src = `${API_BASE}/video_feed`;
        statusBadge.innerText = "Camera Ready (Stream)";
        statusBadge.style.color = "#00d9ff";
    }

    // --- 3. CONTROLS ---

    // A. ROTATE CAMERA (NEW LOGIC)
    const btnRotate = document.getElementById('btnRotate');
    if (btnRotate) {
        btnRotate.onclick = async () => {
            try {
                // Call the new backend endpoint
                const res = await fetch(`${API_BASE}/api/rotate-camera`, { method: 'POST' });
                const data = await res.json();
                statusBadge.innerText = `Rotation: ${data.rotation}°`;
            } catch(e) { 
                console.error("Rotate Failed", e); 
                statusBadge.innerText = "Rotate Error";
            }
        };
    }

    // B. Live Feed (Raw Camera)
    document.getElementById('btnCamera').onclick = async () => {
        stopUIProcessing();
        video.style.display = 'block';
        resImg.style.display = 'none';
        
        // Switch Backend to RAW
        try {
            const fd = new FormData();
            fd.append('mode', 'RAW');
            await fetch(`${API_BASE}/api/set-mode`, { method: 'POST', body: fd });
            statusBadge.innerText = "Live Feed (Raw)";
        } catch(e) { console.error(e); }
    };

    // C. Live AI Mode (Detection Overlay)
    document.getElementById('btnLive').onclick = async () => {
        stopUIProcessing();
        video.style.display = 'block';
        resImg.style.display = 'none';
        
        // Switch Backend to AI
        try {
            const fd = new FormData();
            fd.append('mode', 'AI');
            fd.append('pixels_per_cm', ppcmIn.value);
            fd.append('garment_type', typeIn.value);
            await fetch(`${API_BASE}/api/set-mode`, { method: 'POST', body: fd });
            
            statusBadge.innerText = "Live AI Mode";
            document.getElementById('btnLive').innerText = "Running AI...";
        } catch(e) { console.error(e); }
    };

    // D. Capture Button
    document.getElementById('btnCapture').onclick = async () => {
        statusBadge.innerText = "Processing...";
        
        const fd = new FormData();
        fd.append('use_internal_cam', 'true'); 
        fd.append('pixels_per_cm', parseFloat(ppcmIn.value) || 0);
        fd.append('manual_garment_type', typeIn.value);
        fd.append('save_report', 'false'); 

        try {
            const res = await fetch(`${API_BASE}/process`, {method:'POST', body:fd});
            const data = await res.json();
            if(data.error) throw new Error(data.error);

            handleProcessSuccess(data);
            lastResultData = data; 
            document.getElementById('btnSaveReport').disabled = false;

        } catch(e) { 
            statusBadge.innerText = "Error: " + e.message; 
            alert("Capture Failed: " + e.message);
        }
    };

    // Helper: Handle success data
    function handleProcessSuccess(data) {
        resImg.src = data.measure_image;
        video.style.display = 'none';
        resImg.style.display = 'block';
        
        if(data.detected_size !== 'Unknown') {
            document.getElementById('sizeDisplay').style.display = 'block';
            document.getElementById('sizeValue').innerText = data.detected_size;
            
            let statusText = `${data.confidence}% confident`;
            const sizeVal = document.getElementById('sizeValue');
            
            if (data.qc_status === 'FAIL') {
                statusText += ` | ❌ QC FAIL`;
                sizeVal.style.color = '#ff4444';
                showQCModal(false, data.qc_failures, data.detected_size);
            } else if (data.qc_status === 'PASS') {
                statusText += ` | ✅ QC PASS`;
                sizeVal.style.color = '#00ff88';
            } else {
                sizeVal.style.color = '#00d9ff';
            }
            document.getElementById('confidenceValue').innerText = statusText;
        }

        document.getElementById('thumbDetect').src = data.detect_image;
        document.getElementById('thumbEdge').src = data.edge_image;
        
        updateMeasurementList(data.data);
        statusBadge.innerText = "Capture Complete";
        document.getElementById('btnLive').innerText = "▶️ Live Mode";
    }

    function stopUIProcessing() {
        isLive = false;
        document.getElementById('sizeDisplay').style.display = 'none';
        document.getElementById('btnLive').innerText = "▶️ Live Mode";
    }

    // --- 4. UPLOAD & SAVE ---
    document.getElementById('btnUpload').onclick = () => fileIn.click();
    fileIn.onchange = (e) => { if(e.target.files[0]) { stopUIProcessing(); processFile(e.target.files[0]); } };

    async function processFile(blob) {
        statusBadge.innerText = "Processing File...";
        const fd = new FormData();
        fd.append('file', blob);
        fd.append('pixels_per_cm', parseFloat(ppcmIn.value) || 0);
        fd.append('manual_garment_type', typeIn.value);

        try {
            const res = await fetch(`${API_BASE}/process`, {method:'POST', body:fd});
            const data = await res.json();
            if(data.error) throw new Error(data.error);
            handleProcessSuccess(data);
            lastResultData = data; 
            document.getElementById('btnSaveReport').disabled = false;
        } catch(e) { statusBadge.innerText = "Error"; alert(e.message); }
    }

    document.getElementById('btnSaveReport').onclick = async () => {
        if(!lastResultData || !lastResultData.measure_image) return;
        const btn = document.getElementById('btnSaveReport');
        const originalText = btn.innerText;
        btn.innerText = "Saving...";
        btn.disabled = true;

        try {
            const block = lastResultData.measure_image.split(";");
            const contentType = block[0].split(":")[1];
            const realData = window.atob(block[1].split(",")[1]);
            let array = [];
            for (let i = 0; i < realData.length; i++) array.push(realData.charCodeAt(i));
            const blob = new Blob([new Uint8Array(array)], {type: contentType});

            const fd = new FormData();
            fd.append('file', blob);
            fd.append('pixels_per_cm', ppcmIn.value);
            fd.append('manual_garment_type', typeIn.value);
            fd.append('save_report', 'true');

            const res = await fetch(`${API_BASE}/process`, {method:'POST', body:fd});
            const d = await res.json();
            
            alert(`Report Saved Successfully!\nID: ${d.report_id}`);
            loadReports(); 

        } catch(e) { alert("Error saving report: " + e.message); } 
        finally { btn.innerText = originalText; btn.disabled = false; }
    };

    // --- 5. TABS & HELPERS ---
    function updateMeasurementList(measurements) {
        const list = document.getElementById('measurementsList');
        list.innerHTML = '';
        measurements.forEach(m => {
            list.innerHTML += `<div class="measurement-item">
                <span class="measurement-name">${m.name}</span>
                <span class="measurement-value val" style="color:var(--accent)">${m.value} ${m.unit||'cm'}</span>
            </div>`;
        });
    }

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
            
            if (btn.dataset.tab === 'calibrate') startCalibCamera();
            else stopCalibCamera();
            if (btn.dataset.tab === 'reports') loadReports();
            if (btn.dataset.tab === 'reference') loadReferences();
        };
    });

    // --- GARMENT SELECTOR UPDATE ---
    document.getElementById('garmentSelector').onclick = (e) => {
        if(e.target.classList.contains('garment-btn')) {
            document.querySelectorAll('.garment-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active'); 
            typeIn.value = e.target.dataset.type;
            
            // Set mode to RAW so it doesn't show reference point immediately
            const fd = new FormData();
            fd.append('mode', 'RAW'); 
            fd.append('pixels_per_cm', ppcmIn.value);
            fd.append('garment_type', typeIn.value);
            fetch(`${API_BASE}/api/set-mode`, { method: 'POST', body: fd });
        }
    };

    // --- STYLE / SPEC SELECTOR ---
    // Pushes the chosen spec file to the backend, which saves it as the active
    // data/size_standards.json (same mechanism the online screen's style picker
    // uses) so every capture afterward is checked against the right targets
    // and tolerances, on this page AND the online screen.
    if (styleSelect) {
        styleSelect.onchange = async () => {
            const url = styleSelect.value || '/data/size_standards_3889_pant.json';
            statusBadge.innerText = 'Loading style...';
            try {
                const res = await fetch(`${API_BASE}${url}`);
                if (!res.ok) throw new Error(`Spec file not found on server (${url}, HTTP ${res.status})`);
                const standards = await res.json();
                if (!standards || !standards.units || !standards.trousers) {
                    throw new Error('That file does not look like a valid size_standards spec - not applying it.');
                }
                const fd = new FormData();
                fd.append('mode', 'RAW');
                fd.append('pixels_per_cm', ppcmIn.value);
                fd.append('garment_type', typeIn.value);
                fd.append('standards', JSON.stringify(standards));
                await fetch(`${API_BASE}/api/set-mode`, { method: 'POST', body: fd });
                statusBadge.innerText = 'Style Applied';
            } catch (e) {
                statusBadge.innerText = 'Style Load Error';
                alert('Could not load that style file: ' + e.message);
            }
        };
    }

    // --- 6. CALIBRATION ---
    function startCalibCamera() {
        const v = document.getElementById('calibrateVideo');
        if (!v.src) v.src = `${API_BASE}/video_feed`;
    }
    function stopCalibCamera() {
        const v = document.getElementById('calibrateVideo');
        v.src = '';
    }

    document.getElementById('btnCalibrateCapture').onclick = () => {
        const v = document.getElementById('calibrateVideo');
        const c = document.createElement('canvas');
        c.width = v.naturalWidth; c.height = v.naturalHeight;
        c.getContext('2d').drawImage(v, 0, 0);
        c.toBlob(performCalibration, 'image/jpeg');
    };
    
    async function performCalibration(blob) {
        const statusEl = document.getElementById('calibrateStatus');
        statusEl.innerText = 'Detecting A4 paper...';
        const fd = new FormData();
        fd.append('file', blob);
        fd.append('t1', document.getElementById('calibrateT1').value);
        fd.append('t2', document.getElementById('calibrateT2').value);
        
        try {
            const res = await fetch(`${API_BASE}/api/calibrate`, {method:'POST', body:fd});
            const data = await res.json();
            document.getElementById('calibrateResult').src = data.debug_image;
            if(data.success && data.pixels_per_cm) {
                statusEl.innerText = data.message;
                document.getElementById('calibrateCurrentValue').value = data.pixels_per_cm; 
                document.getElementById('btnApplyCalibration').disabled = false;
            } else {
                statusEl.innerText = data.message || 'A4 paper not detected';
            }
        } catch(e) { statusEl.innerText = 'Error: ' + e.message; }
    }
    
    document.getElementById('btnApplyCalibration').onclick = () => {
        const val = document.getElementById('calibrateCurrentValue').value;
        if(val) { ppcmIn.value = val; alert(`✓ Calibration Applied! Value: ${val} px/cm`); }
    };

    // --- 7. REFERENCE & REPORTS ---
    const refVideo = document.getElementById('refVideo');
    document.getElementById('btnRefCamera').onclick = () => {
         if (!refVideo.src) refVideo.src = `${API_BASE}/video_feed`;
         refVideo.style.display = 'block';
         document.getElementById('refResultImage').style.display = 'none';
    };

    document.getElementById('btnRefMeasure').onclick = () => {
        const c = document.createElement('canvas');
        c.width = refVideo.naturalWidth; c.height = refVideo.naturalHeight;
        c.getContext('2d').drawImage(refVideo, 0, 0);
        c.toBlob(processReferenceFrame, 'image/jpeg');
    };
    
    async function processReferenceFrame(blob) {
        const fd = new FormData();
        fd.append('file', blob);
        fd.append('pixels_per_cm', parseFloat(ppcmIn.value) || 0);
        fd.append('manual_garment_type', document.getElementById('refGarmentType').value);

        try {
            const res = await fetch(`${API_BASE}/process`, {method:'POST', body:fd});
            const data = await res.json();
            document.getElementById('refResultImage').src = data.measure_image;
            refVideo.style.display = 'none';
            document.getElementById('refResultImage').style.display = 'block';
            const list = document.getElementById('refMeasurementsList');
            list.innerHTML = '';
            data.data.forEach(m => { list.innerHTML += `<div class="measurement-item">${m.name}: ${m.value} cm</div>`; });
            window.refBlob = blob; window.refData = data;
        } catch(e) { console.error(e); }
    }
    
    document.getElementById('btnSaveReference').onclick = async () => {
        const size = document.getElementById('refSize').value;
        if (!size || !window.refBlob) { alert("Capture and enter size first"); return; }
        const fd = new FormData();
        fd.append('file', window.refBlob); 
        fd.append('garment_type', document.getElementById('refGarmentType').value); 
        fd.append('size', size); 
        fd.append('measurements', JSON.stringify(window.refData.data));
        await fetch(`${API_BASE}/api/reference-garment`, {method:'POST', body:fd});
        alert("Reference Saved!");
        loadReferences();
    };

    document.getElementById('btnRefreshReports').onclick = loadReports;
    async function loadReports() {
        const tbody = document.getElementById('reportsTableBody');
        tbody.innerHTML = '<tr><td colspan="6">Loading...</td></tr>';
        try {
            const res = await fetch(`${API_BASE}/api/reports`);
            const data = await res.json();
            tbody.innerHTML = '';
            data.forEach(r => {
                let statusHtml = r.qc_status === 'PASS' ? '<span style="color:#00ff88">PASS</span>' : '<span style="color:#ff4444">FAIL</span>';
                tbody.innerHTML += `<tr><td>${new Date(r.timestamp).toLocaleDateString()}</td><td>${r.garment_type}</td><td>${r.detected_size}</td><td>${statusHtml}</td><td><button onclick="alert('TODO: Show Detail')">View</button></td></tr>`;
            });
        } catch(e) { tbody.innerHTML = '<tr><td colspan="6">Error loading reports</td></tr>'; }
    }

    const csvTypeSelect = document.getElementById('csvGarmentType');
    if(csvTypeSelect) csvTypeSelect.onchange = updateCsvTemplateHelp;
    
    function updateCsvTemplateHelp() {
        const type = csvTypeSelect.value;
        const codeBlock = document.getElementById('csvTemplateCode');
        if (garmentConfig && garmentConfig[type]) {
            const headers = ["Size", ...garmentConfig[type].measurements];
            codeBlock.innerText = headers.join(', ');
        }
    }
    
    document.getElementById('btnImportCSV').onclick = async () => {
        const f = document.getElementById('csvFileInput').files[0];
        if(!f) return;
        const fd = new FormData();
        fd.append('file', f);
        fd.append('garment_type', csvTypeSelect.value);
        await fetch(`${API_BASE}/api/import-size-csv`, {method:'POST', body:fd});
        alert("CSV Imported");
    };

    function showQCModal(isPass, failures, size) {
        qcModal.style.display = 'flex';
        qcList.innerHTML = '';
        if (isPass) {
            qcTitle.innerText = "QC PASSED"; qcTitle.style.color = "#00ff88"; 
            qcMessage.innerText = `Garment matches Size ${size} standards.`;
        } else {
            qcTitle.innerText = "QC FAILED"; qcTitle.style.color = "#ff4444"; 
            qcMessage.innerText = `Garment failed Size ${size} check:`;
            failures.forEach(f => { const li = document.createElement('li'); li.innerText = f; qcList.appendChild(li); });
        }
    }
    document.querySelector('.close-modal').onclick = () => qcModal.style.display = 'none';
    window.onclick = (e) => { if(e.target == qcModal) qcModal.style.display = 'none'; };
});