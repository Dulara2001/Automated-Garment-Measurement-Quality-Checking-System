# Automated Garment Measurement & Quality-Checking System (ELIoT-EYE / GarmentQC AI)

A computer-vision system that measures garments automatically for factory quality control.

An overhead camera photographs a garment (a shirt or a pair of trousers) lying flat on a table.
An AI model finds keypoints on the garment (collar, cuffs, waist, hems, crotch, ...), the engine
measures straight-line distances between those points, converts the result from pixels into real
units (cm / inches) using a camera calibration, and checks each measurement against the customer's
size specification to give a **PASS / FAIL** result — no tape measure or manual comparison needed.

It runs as a fullscreen kiosk app on a Windows PC next to the measuring table, so a factory QC
operator can lay a garment down, capture a photo, and get a result in seconds.

## What it does

- **Captures** a photo of a garment from a camera mounted above a table.
- **Detects ~294 keypoints** on the garment with an AI landmark model (`models/fashion_landmark.onnx`).
- **Removes the background** with U²-Net (`models/u2net.onnx`) so only the garment is measured.
- **Resolves each required measurement point** from the raw keypoints (e.g. the true waist corner,
  the crotch seam, the hem edge), refining noisy AI guesses against the garment's actual outline.
- **Measures** the straight-line pixel distance between the two points that make up each
  measurement, averaged across 3 captured frames for stability.
- **Converts pixels → real units** using a camera calibration (a reference object of known size in
  the photo gives a pixels-per-centimetre value).
- **Classifies the garment's size** and compares each measurement against the customer's spec sheet
  and tolerance, producing PASS / FAIL per measurement and overall.
- **Saves a QC report** (with an annotated debug image showing every point and line used) and can
  sync it to the cloud (Supabase + Cloudflare object storage) when the station is online.
- **Runs offline** — captures and reports are queued locally and synced later if there's no network.

## Garments supported

| Garment | Status |
|---|---|
| Shirts (short-sleeve top) | Fully measured — neck, shoulder, chest, sleeve, body length, etc. |
| Trousers | Fully measured — waist, leg opening, hip, inseam, thigh, front rise, back rise, fly length |

Trouser measurements are mapped to the customer's own POM (Point of Measure) codes in
`data/size_standards_3889_pant.json`; the engine's internal letter codes (below) are translated to
those customer codes when a report is generated.

<details>
<summary>Internal measurement codes (click to expand)</summary>

**Shirt / top**

| Code | Measurement |
|---|---|
| A | Neck width |
| B | Sleeve opening (short) |
| C | Chest, armpit to armpit |
| D | Centre-front body length (shoulder to bottom edge) |
| E | Bottom sweep (waist), straight across |
| F | Sleeve length from shoulder seam |
| G | Upper arm |
| H / z | Shoulder width (manual / auto-detected) |
| I | Upper arm position (2-piece garments) |
| J | Side seam, armpit to hem |

**Trousers**

| Code | Measurement |
|---|---|
| J | Waist width |
| K / L | Leg opening (left / right) |
| M | Hip width |
| N / O | Leg length (left / right) |
| P / Q | Inseam (right / left) |
| R | Leg width at knee |
| S | Front rise |
| T | Thigh, 1" below crotch |
| U | Back rise *(needs a photo of the back of the garment)* |
| V | Fly length *(experimental)* |

</details>

## How it works, step by step

```
Operator lays garment flat on the table and presses capture
        │
        ▼
Camera captures 3 frames  ──────────────────────────────────────────────
        │                                                                │
        ▼                                                                │
AI landmark model (inference.py) → ~294 keypoints per frame              │
        │  (each keypoint = an id, an x/y position, and a confidence)    │
        ▼                                                                │
U²-Net background removal → a mask of just the garment (once per capture)│
        │                                                                │
        ▼                                                                │
Measurement engine (processing_engine.py):                               │
  1. keep only keypoints with confidence > 0.1, inside their expected area
  2. refine points against the garment's real outline
     (e.g. lock the crotch to where the operator aligned it on-screen)
  3. resolve the two points that define each measurement
  4. average each point's position across the 3 frames
  5. take the straight-line pixel distance, convert to cm/inches
        │
        ▼
Compare to the customer's size spec + tolerance → PASS / FAIL
        │
        ▼
Save the report + a debug image with every point and line drawn on it
```

The system is **keypoint-driven, not outline-driven**: the AI always returns the same ~294 numbered
points, and it's the configuration in `garment_config.py` that decides which numbers mean what for a
given garment type, and which pairs of resolved points make up each measurement.

## Tech stack

- **Backend**: Python, FastAPI (`endpoints_server.py`) — serves the measurement API and the camera
  feed to the UI.
- **Computer vision**: OpenCV, ONNX Runtime running two models — a fashion landmark/keypoint model
  and U²-Net for background removal.
- **Desktop app**: PyWebview (fullscreen kiosk window embedding the web UI), launched by
  `windows_test.py`.
- **UI**: served from `static/` (HTML/CSS/JS).
- **Storage/sync**: Supabase (database/auth) and Cloudflare R2 (via `boto3`) for uploading QC
  reports and photos when online; results queue locally otherwise.
- **Calibration**: a reference object of known size in-frame converts pixel measurements to real
  units (`calibrator.py`).

## Project structure

```
main.py                  Backend/API entry point
windows_test.py           Kiosk app entry point (opens the fullscreen window)
endpoints_server.py       FastAPI routes (camera, capture, calibration, wifi, reports, updates)
inference.py              Runs the AI landmark model on a captured frame
processing_engine.py      Core measurement engine (turns keypoints into measurements)
garment_config.py         Defines measurement letter codes, point maps, and per-garment logic
shirt_processor.py        Shirt-specific point refinement
trouser_processor.py      Trouser-specific point refinement
calibrator.py             Pixel ⇄ real-world unit calibration
camera_manager.py         Camera capture handling
qc_validator.py           Compares measurements to spec + tolerance, gives PASS/FAIL
sync_manager.py           Uploads reports/photos to the cloud when online
wifi_manager.py           Wi-Fi connection management for the kiosk PC
updater.py                Checks for and applies app updates
loading/                  Kiosk splash/loading screen + slideshow
static/                   Kiosk web UI (HTML/CSS/JS)
models/                   The two ONNX models (landmark detection, background removal)
data/                     Calibration, device config, and per-customer size standards (JSON)
builder_tools/            Scripts that package this app into a standalone Windows .exe/installer
patch_input/              Tool for building small update patches for already-installed stations
```

## Running it

```bash
pip install -r requirements.txt
python windows_test.py
```

This opens the fullscreen kiosk window, starts the local API server, and connects to the camera.
First start can take a minute or two while the AI models load.

Some optional features need extra setup before they'll work:

- **Cloud sync** — set up Supabase credentials for `sync_manager.py` to upload reports.
- **Auto-update** — the updater and patch tools need an encryption key supplied via an environment
  variable (kept out of source on purpose):
  ```bash
  set GARMENT_QC_ENCRYPTION_KEY=your-own-key-here
  ```
  Everything else (capturing, measuring, PASS/FAIL, local reports) works without it.

## License

This codebase is proprietary (see copyright headers in individual files) and not licensed for reuse
or redistribution without permission from its owner.
