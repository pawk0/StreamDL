# StreamDL - Video Stream Downloader (Browser Extension + Local Server)

A modern, robust personal media archiving solution that captures video streams directly from websites, queues them in a local Python server, and downloads the best quality versions using `yt-dlp` and `ffmpeg`.

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│                   BROWSER EXTENSION                    │
│  - Network Request Sniffer (.m3u8, .mpd, mp4)          │
│  - Master Playlist Prioritization                      │
│  - Right-click Context Menu ("Download with yt-dlp")   │
│  - Clean Popup UI (Quality & Format Selection)         │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP POST /api/download
                           │ (with URL, Referer, Quality)
                           ▼
┌────────────────────────────────────────────────────────┐
│               LOCAL PYTHON SERVER (Flask)              │
│                 http://localhost:7921                  │
│  - REST API & Web Dashboard Host                       │
│  - Configurable Concurrency Manager (e.g. 1-10 max)    │
│  - FIFO Queue: Parallel downloads with auto-dispatch   │
│  - yt-dlp Engine with Real-time Progress Hooks         │
└──────────────────────────┬─────────────────────────────┘
                           │ Merges best video + audio
                           ▼
┌────────────────────────────────────────────────────────┐
│                 STORAGE / FILE SYSTEM                  │
│  - Saved to ~/Downloads/VideoDL (Configurable)         │
│  - High quality MP4, MKV, or MP3 files                 │
└────────────────────────────────────────────────────────┘
```

---

## Features

- **Smart Stream Sniffing**: Automatically captures HLS (`.m3u8`), DASH (`.mpd`), and direct video files (`.mp4`, `.webm`) playing on any website.
- **Master Playlist Prioritization**: Intelligently pinpoints master playlists (`master.m3u8`, `playlist.m3u8`) so `yt-dlp` receives the full adaptive manifest and selects the highest resolution/bitrate available.
- **Concurrent Downloads with Queuing**: Configure how many downloads run in parallel (default: 3). Additional items enter the queue and start automatically as slots free up.
- **Modern Web Dashboard**: Real-time progress tracking, live download speed, ETA, progress bars, cancellation, download history, and settings at `http://localhost:7921`.
- **Referer & Header Passing**: Automatically passes `Referer` and `User-Agent` headers from the browser to prevent HTTP 403 Forbidden errors from CDN token checkers.
- **Quality & Format Controls**: Download in Best Available, 1080p FHD, 720p HD, 480p SD, or extract pure audio as MP3.
- **Streaming Provider Mapping**: Map rotating CDN domains to custom provider concurrency limits directly from the dashboard via the quick `+` button next to detected domains.
- **1-Click Folder & File Access**: Direct buttons to open the download folder in Windows File Explorer or play the completed media file.

---

## Getting Started

### Prerequisites
- **Python 3.10+** (Python 3.13 and 3.14 are verified and supported)
- **ffmpeg** (Used for merging video and audio streams into a single MP4)

---

### Step 1: Set Up & Start the Server

We provide automated 1-click Windows batch scripts:

1. **Initial Setup (One-time)**:
   Double-click `setup.bat` or run:
   ```powershell
   .\setup.bat
   ```
   *This automatically creates the `.venv` virtual environment and installs `flask`, `flask-cors`, and `yt-dlp`.*

2. **Start the Local Server**:
   Double-click `run_server.bat` or run:
   ```powershell
   .\run_server.bat
   ```
   *The server starts listening on `http://localhost:7921`.*

3. Open your browser and navigate to:
   **[http://localhost:7921](http://localhost:7921)** to view the Web UI dashboard.

---

### Step 2: Install the Browser Extension

StreamDL supports **Google Chrome, Microsoft Edge, Brave, Opera**, and **Mozilla Firefox**.

#### For Chromium Browsers (Chrome, Edge, Brave, Opera):
1. Open your browser and go to `chrome://extensions` (or `edge://extensions`).
2. Enable **Developer mode** using the toggle switch in the top-right corner.
3. Click **Load unpacked** in the top-left corner.
4. Select the `extension` folder inside this project directory:
   `c:\Users\Pawel\Desktop\projects\video_dl\extension`
5. Pin the **StreamDL** icon to your browser toolbar.

#### For Mozilla Firefox:
1. Open Firefox and navigate to `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on...**.
3. In the file dialog, navigate to `c:\Users\Pawel\Desktop\projects\video_dl\extension` and select `manifest.json`.
4. Pin the **StreamDL** icon to your browser toolbar.

---

## How to Use

### Method 1: Using the Browser Extension (Recommended)
1. Navigate to any website containing video (e.g. streaming site, video player, news article).
2. Play or start buffering the video.
3. Click the **StreamDL** extension icon in your browser toolbar.
   - The popup displays the detected stream (highlighting master playlists with a ⭐ badge).
   - Choose your preferred **Quality** (Default: *Best Quality*) and **Format** (*MP4*).
   - Click **Download Stream**.
4. You can immediately browse to another website and repeat! The local server will download up to your concurrent limit and queue any extra tasks automatically.

### Method 2: Right-Click Context Menu
- Right-click anywhere on a video element, video link, or webpage.
- Select **"Download with yt-dlp"**.
- The video will automatically be queued on your local server.

### Method 3: Via the Web Dashboard
1. Go to `http://localhost:7921`.
2. Paste any video URL (YouTube, Vimeo, Twitter, direct `.m3u8` link, etc.) into the **Add Download** input box.
3. Click **Download**.

---

## Configuration & Settings

Click the **Settings** gear icon in the Web UI (`http://localhost:7921`) to customize:
- **Max Concurrent Downloads**: Slider from 1 to 10 (changes take effect immediately for queued items).
- **Streaming Providers & Domain Patterns**: Add custom providers, wildcard CDN patterns, and per-provider concurrency limits, or map unconfigured domains directly using the `+` button next to the domain.
- **Download Destination Folder**: Custom path on your computer (defaults to `~/Downloads/VideoDL`).
- **Default Quality & Format**: Preferred preset for new downloads.

Settings are saved in `settings.json`.

---

## Project Structure

```
video_dl/
├── .venv/                      # Python virtual environment
├── requirements.txt            # Python dependencies (flask, flask-cors, yt-dlp)
├── setup.bat                   # 1-click environment setup script
├── run_server.bat              # 1-click server launch script
├── run_server.py               # Server entry point
├── settings.json               # Persisted user settings
│
├── server/                     # Local Flask Server
│   ├── app.py                  # REST API & static routes
│   ├── config.py               # Settings loader & provider matcher
│   ├── downloader.py           # Thread-safe queue dispatcher & public facade
│   ├── engine.py               # yt-dlp option configuration & execution engine
│   ├── task.py                 # DownloadTask model & progress state
│   ├── cleanup.py              # Windows handle release & temp file cleanup
│   ├── resolvers.py            # Video host resolvers (e.g. Doodstream)
│   ├── utils.py                # Pure formatting & filename sanitation utils
│   ├── static/
│   │   ├── css/style.css       # Modern dark glassmorphic dashboard CSS
│   │   └── js/app.js           # Real-time polling & UI controller
│   └── templates/
│       └── index.html          # Dashboard HTML template
│
├── extension/                  # Cross-Browser WebExtension (Chrome, Edge, Firefox, Brave)
│   ├── manifest.json           # Manifest V3 configuration (dual Chromium + Firefox MV3)
│   ├── background.js           # Network request sniffer & queue client
│   ├── content.js              # DOM media scanner
│   ├── utils.js                # Shared stream analysis, header derivation & storage utils
│   ├── icons/                  # 16px, 48px, 128px icons
│   └── popup/
│       ├── popup.html          # Extension popup UI
│       ├── popup.css           # Modern popup styling
│       └── popup.js            # Popup controller & server health check
│
└── tests/                      # Automated test suite (pytest + Playwright)
    ├── conftest.py             # Test isolation & environment fixtures
    ├── fixtures.py             # Shared mock data & test helpers
    ├── extension/              # Browser extension test suite
    │   ├── test_manifest.py    # Manifest V3 & cross-browser compatibility tests
    │   └── test_utils.py       # Extension JS utility & stream analysis tests (Playwright)
    └── server/                 # Local server unit & integration tests
        ├── test_server.py      # REST API endpoint tests
        ├── test_concurrency.py # Concurrency limit & queue dispatcher tests
        ├── test_duplicate_tasks.py # URL normalization & deduplication tests
        ├── test_headers.py     # Request header building & origin derivation tests
        ├── test_mock_downloader.py # Queue state machine & download lifecycle tests
        ├── test_providers.py   # Domain pattern matching & concurrency tests
        ├── test_remote_control_php.py # Video host & resolver tests
        ├── test_cancellation_cleanup.py # Handle release & temp file cleanup tests
        └── test_live_download.py # Real HLS stream download test (live mark)
```

---

## Testing

StreamDL includes a comprehensive test suite covering the local Flask server, concurrency dispatcher, cancellation cleanup, and the browser extension.

Run the test suite using pytest:

```powershell
# Run all fast unit and integration tests (230+ tests)
.\.venv\Scripts\python.exe -m pytest

# Run browser extension unit tests (headless Playwright)
.\.venv\Scripts\python.exe -m pytest tests/extension/

# Run server-side unit tests
.\.venv\Scripts\python.exe -m pytest tests/server/
```

---

## Privacy Policy

StreamDL is built with a strict **local-first, privacy-by-design** philosophy:

- **100% Local Execution**: All stream sniffing, format analysis, and video downloads occur entirely on your machine.
- **Zero Telemetry**: No analytics, tracking beacons, error reports, or telemetry data are collected or sent to any remote server.
- **Direct Connection Only**: The browser extension communicates strictly with your local Python server at `http://localhost:7921`. Stream downloads are fetched directly by `yt-dlp` from the media provider's CDN—no intermediary proxy or cloud relay is ever used.
- **Minimal Permissions**: Extension permissions (`webRequest`, `storage`, `activeTab`, `contextMenus`, `notifications`) are used exclusively for core functionality on your local computer.

For complete details, see the full [Privacy Policy](PRIVACY.md).

---

## License

This project is licensed under the [MIT License](LICENSE).

