// StreamDL Extension Service Worker
const SERVER_URL = "http://localhost:7921";
const streamsByTab = new Map();

// Helper to extract base stream directory key (e.g. protocol://host/path/without_filename)
function getStreamKey(url) {
  try {
    const u = new URL(url);
    const segments = u.pathname.split("/").filter(Boolean);
    segments.pop(); // remove filename
    return `${u.origin}/${segments.join("/")}`;
  } catch (e) {
    return url.split("?")[0];
  }
}

// Helper to determine stream type, master vs variant status
function analyzeStreamUrl(url) {
  const lower = url.toLowerCase();
  
  // Exclude segment chunks
  if (
    lower.includes(".ts") ||
    lower.includes(".m4s") ||
    lower.includes(".aac") ||
    lower.includes("segment-") ||
    lower.includes("/seg-") ||
    lower.includes("/fragment")
  ) {
    return null;
  }

  let type = "other";
  let isMaster = false;
  let isVariant = false;

  const pathname = url.split("?")[0].toLowerCase();
  const filename = pathname.split("/").pop() || "";

  if (lower.includes(".m3u8")) {
    type = "HLS (.m3u8)";
    
    // Check if this is a variant/child playlist (e.g. index-f2-v1-a1.m3u8, 720p.m3u8, chunklist)
    if (
      /[-_][fva]\d+/i.test(filename) ||
      filename.includes("chunklist") ||
      filename.includes("rendition") ||
      filename.includes("tracks-") ||
      /\b(1080p|720p|480p|360p|240p)\.m3u8/i.test(filename)
    ) {
      isVariant = true;
      isMaster = false;
    } else if (
      filename === "master.m3u8" ||
      filename === "playlist.m3u8" ||
      filename === "manifest.m3u8" ||
      filename === "index.m3u8" ||
      filename === "main.m3u8" ||
      filename.includes("master") ||
      filename.includes("manifest")
    ) {
      isMaster = true;
    }
  } else if (lower.includes(".mpd")) {
    type = "DASH (.mpd)";
    isMaster = true;
  } else if (lower.includes(".mp4")) {
    type = "MP4 Video";
  } else if (lower.includes(".webm")) {
    type = "WebM Video";
  } else {
    return null;
  }

  return { type, isMaster, isVariant, filename };
}

// Intercept network requests for media stream manifests and video URLs
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0) return;

    const streamInfo = analyzeStreamUrl(details.url);
    if (!streamInfo) return;

    let tabStreams = streamsByTab.get(details.tabId) || [];
    const baseKey = getStreamKey(details.url);

    // Check if we already have a stream from this exact video directory
    const existingIndex = tabStreams.findIndex((s) => getStreamKey(s.url) === baseKey);

    if (existingIndex !== -1) {
      const existing = tabStreams[existingIndex];
      // If the incoming stream is a MASTER playlist and the existing is only a variant, upgrade it!
      if (streamInfo.isMaster && !existing.isMaster) {
        tabStreams[existingIndex] = {
          url: details.url,
          type: streamInfo.type,
          isMaster: true,
          filename: streamInfo.filename,
          timestamp: Date.now(),
          initiator: details.initiator || details.documentUrl || "",
        };
      } else {
        // Already have the master or an identical stream from this video session, ignore duplicate variant
        return;
      }
    } else {
      // New stream from a distinct video/source
      const streamObj = {
        url: details.url,
        type: streamInfo.type,
        isMaster: streamInfo.isMaster,
        filename: streamInfo.filename,
        timestamp: Date.now(),
        initiator: details.initiator || details.documentUrl || "",
      };

      if (streamInfo.isMaster) {
        tabStreams.unshift(streamObj);
      } else {
        tabStreams.push(streamObj);
      }
    }

    // Limit memory to 20 streams per tab
    if (tabStreams.length > 20) {
      tabStreams = tabStreams.slice(0, 20);
    }

    streamsByTab.set(details.tabId, tabStreams);
    updateBadge(details.tabId, tabStreams.length);
  },
  {
    urls: [
      "*://*/*.m3u8*",
      "*://*/*.mpd*",
      "*://*/*.mp4*",
      "*://*/*.webm*"
    ]
  }
);

// Update badge count on extension icon
function updateBadge(tabId, count) {
  if (count > 0) {
    chrome.action.setBadgeText({ tabId, text: String(count) });
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#6366f1" });
  } else {
    chrome.action.setBadgeText({ tabId, text: "" });
  }
}

// Clean up streams when tab is closed or navigated
chrome.tabs.onRemoved.addListener((tabId) => {
  streamsByTab.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    streamsByTab.delete(tabId);
    updateBadge(tabId, 0);
  }
});

// Setup Context Menu
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "streamdl-download",
    title: "Download with yt-dlp",
    contexts: ["page", "video", "link"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "streamdl-download") {
    const targetUrl = info.srcUrl || info.linkUrl || info.pageUrl || (tab && tab.url);
    if (!targetUrl) return;

    await sendDownloadRequest({
      url: targetUrl,
      title: tab ? tab.title : undefined,
      referer: tab ? tab.url : undefined
    });
  }
});

// Handle messages from Popup or Content Script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "GET_TAB_STREAMS") {
    const tabId = message.tabId;
    const streams = streamsByTab.get(tabId) || [];
    sendResponse({ streams });
    return true;
  } else if (message.action === "SEND_DOWNLOAD") {
    sendDownloadRequest(message.payload)
      .then((res) => sendResponse(res))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  } else if (message.action === "REGISTER_DOM_MEDIA") {
    const tabId = sender.tab ? sender.tab.id : null;
    if (tabId) {
      const streamInfo = analyzeStreamUrl(message.url);
      if (streamInfo) {
        let tabStreams = streamsByTab.get(tabId) || [];
        if (!tabStreams.some((s) => s.url === message.url)) {
          tabStreams.unshift({
            url: message.url,
            type: streamInfo.type,
            isMaster: streamInfo.isMaster,
            timestamp: Date.now()
          });
          streamsByTab.set(tabId, tabStreams);
          updateBadge(tabId, tabStreams.length);
        }
      }
    }
  }
});

// Send download command to local Flask server
async function sendDownloadRequest({ url, title, referer, quality = "best", format = "mp4" }) {
  try {
    const headers = {};
    if (referer) {
      headers["Referer"] = referer;
    }

    const res = await fetch(`${SERVER_URL}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        title,
        quality,
        format,
        headers
      })
    });

    if (!res.ok) {
      throw new Error(`Server returned status ${res.status}`);
    }

    const data = await res.json();
    return data;
  } catch (err) {
    console.error("Failed to connect to local server:", err);
    throw new Error(
      "Local server is offline or unreachable at http://localhost:7921. Make sure run_server.bat is running."
    );
  }
}
