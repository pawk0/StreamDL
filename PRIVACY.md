# Privacy Policy for StreamDL

**Last updated: September 2026**

StreamDL is an open-source personal media archiving tool comprising a browser companion extension and a local Python server. We believe your personal browsing habits, media choices, and network traffic should remain completely private.

---

## Summary of Core Principles

- **100% Local Processing**: All stream sniffing, queue orchestration, format selection, and media downloading occur entirely on your own computer.
- **Zero Telemetry & Analytics**: StreamDL contains no analytics code, trackers, telemetry beacons, crash reporters, or third-party tracking scripts.
- **No Remote Servers**: We do not operate or connect to any remote StreamDL servers or cloud databases. The browser extension only communicates with your own local machine (`http://localhost:7921` or user-defined local port).
- **No Data Sale or Sharing**: None of your browsing history, media URLs, downloaded content, IP addresses, or personal information is ever collected, stored remotely, shared, or sold.

---

## Browser Extension Permissions & Purpose

The StreamDL browser companion extension requests only the minimum necessary permissions to function:

| Permission | Purpose |
| :--- | :--- |
| `webRequest` | Detects media manifests (`.m3u8`, `.mpd`) and video streams (`.mp4`, `.webm`) loaded by web players on pages you visit, and reads necessary session headers (`Referer`, `Origin`, `User-Agent`) so your local server can download streams without HTTP 403 Forbidden errors. |
| `storage` | Stores your local extension preferences (e.g., custom local server port, cached provider definitions). Data is stored exclusively in `chrome.storage.local` on your device. |
| `activeTab` & `tabs` | Reads the title and URL of the active tab when you click the extension popup to display stream context and let you queue downloads with one click. |
| `contextMenus` | Provides the convenient right-click context menu option ("Download with yt-dlp") to queue a video link directly to your local server. |
| `notifications` | Displays optional local desktop notifications when a download completes or fails. |
| `host_permissions` (`<all_urls>`, `localhost`) | Required to monitor media network requests across arbitrary websites and send download commands to your local server (`http://localhost:7921/*` and `http://127.0.0.1:7921/*`). |

---

## How Data Flows

1. **Detection**: When you visit a website containing media, the extension inspects network requests locally to identify adaptive streaming playlists (`.m3u8`, `.mpd`).
2. **Local Queueing**: When you click "Download Stream" or use the context menu, the extension sends an HTTP POST request containing the media URL, title, and request headers directly to your local server at `http://localhost:7921/api/download`.
3. **Downloading**: The local Python server invokes `yt-dlp` to download and merge the media files directly to your configured local directory (defaults to `~/Downloads/VideoDL`).
4. **Media Host Communication**: Stream requests are made directly between your local computer and the video host CDN. StreamDL acts as a direct client, exactly as if your browser were playing the media. No proxy, relay, or intermediary server is ever used.

---

## Local Data Storage

- **Server Configuration**: User settings (such as download paths, concurrency limits, and provider definitions) are saved locally in `settings.json` within your project folder.
- **Downloaded Media**: Media files are saved exclusively to the destination folder you configure on your local file system.
- **Logs**: Download task status and logs are kept strictly in local memory and can be cleared at any time from the web dashboard.

---

## Open Source Transparency

StreamDL is fully open-source. The complete code for both the browser extension and the backend server is available in this repository for inspection, verification, and local compilation.

---

## Contact & Inquiries

For questions or security concerns regarding StreamDL, open an issue in the project's repository.
