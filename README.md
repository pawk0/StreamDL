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
- **1-Click Folder & File Access**: Direct buttons to open the download folder in Windows File Explorer or play the completed media file.

---

## Getting Started

### Prerequisites
- **Python 3.10+** (Python 3.13 is verified and supported)
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

Works with Google Chrome, Microsoft Edge, Brave, Opera, and any Chromium-based browser.

1. Open your browser and go to `chrome://extensions` (or `edge://extensions`).
2. Enable **Developer mode** using the toggle switch in the top-right corner.
3. Click **Load unpacked** in the top-left corner.
4. Select the `extension` folder inside this project directory:
   `c:\Users\Pawel\Desktop\projects\video_dl\extension`
5. Pin the **StreamDL** icon to your browser toolbar.

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
├── extension/                  # Chrome/Chromium Browser Extension
│   ├── manifest.json           # Manifest V3 configuration
│   ├── background.js           # Network request sniffer & queue client
│   ├── content.js              # DOM media scanner
│   ├── icons/                  # 16px, 48px, 128px icons
│   └── popup/
│       ├── popup.html          # Extension popup UI
│       ├── popup.css           # Modern popup styling
│       └── popup.js            # Popup controller & server health check
│
└── tests/                      # Automated unit & integration tests
    ├── test_server.py          # API endpoint tests
    ├── test_concurrency.py     # Concurrency limit & queue dispatcher tests
    └── test_live_download.py   # Real HLS stream download test
```
