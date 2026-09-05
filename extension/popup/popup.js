const SERVER_URL = "http://localhost:7921";

document.addEventListener("DOMContentLoaded", async () => {
  // DOM Elements
  const serverStatus = document.getElementById("server-status");
  const serverStatusText = document.getElementById("server-status-text");
  const pageTitle = document.getElementById("page-title");
  const pageUrl = document.getElementById("page-url");
  
  const streamTypeBadge = document.getElementById("stream-type-badge");
  const streamUrlText = document.getElementById("stream-url-text");
  const groupOtherStreams = document.getElementById("group-other-streams");
  const selectStreamChoice = document.getElementById("select-stream-choice");
  
  const selectQuality = document.getElementById("select-quality");
  const selectFormat = document.getElementById("select-format");
  const btnDownloadStream = document.getElementById("btn-download-stream");
  const btnDownloadStreamLabel = document.getElementById("btn-download-stream-label");
  const btnDownloadPage = document.getElementById("btn-download-page");
  
  const messageBanner = document.getElementById("message-banner");
  const linkDashboard = document.getElementById("link-dashboard");

  let activeTab = null;
  let detectedStreams = [];
  let currentStreamUrl = null;

  // Banner display helper
  function showBanner(text, type = "success") {
    messageBanner.className = `message-banner ${type}`;
    messageBanner.textContent = text;
    setTimeout(() => {
      messageBanner.className = "message-banner";
    }, 4500);
  }

  // Check Server Health
  async function checkServer() {
    try {
      const res = await fetch(`${SERVER_URL}/api/status`, { signal: AbortSignal.timeout(2000) });
      if (res.ok) {
        const data = await res.json();
        serverStatus.className = "server-status online";
        serverStatusText.textContent = `Online (${data.active_count} active)`;
        return true;
      }
    } catch (e) {
      // offline
    }
    serverStatus.className = "server-status offline";
    serverStatusText.textContent = "Server Offline";
    return false;
  }

  // Get active tab info
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs && tabs.length > 0) {
    activeTab = tabs[0];
    pageTitle.textContent = activeTab.title || "Active Tab";
    pageUrl.textContent = activeTab.url || "";
  }

  await checkServer();

  // Request detected streams from background service worker
  if (activeTab && activeTab.id) {
    chrome.runtime.sendMessage(
      { action: "GET_TAB_STREAMS", tabId: activeTab.id },
      (response) => {
        if (chrome.runtime.lastError || !response) {
          streamUrlText.textContent = "Could not reach background worker.";
          return;
        }

        detectedStreams = response.streams || [];
        if (detectedStreams.length > 0) {
          setupStreamSelection(detectedStreams);
        } else {
          streamTypeBadge.textContent = "None";
          streamUrlText.textContent = "No stream captured yet. Play video on the page or use 'Download Page URL'.";
          btnDownloadStream.disabled = true;
        }
      }
    );
  }

  function setupStreamSelection(streams) {
    btnDownloadStream.disabled = false;
    currentStreamUrl = streams[0].url;

    // Show stream type
    const primary = streams[0];
    streamTypeBadge.textContent = primary.isMaster ? "⭐ Master Playlist" : primary.type;
    streamUrlText.textContent = primary.url;

    if (streams.length > 1) {
      groupOtherStreams.style.display = "flex";
      selectStreamChoice.innerHTML = "";
      streams.forEach((s, idx) => {
        const opt = document.createElement("option");
        opt.value = s.url;
        opt.textContent = `${s.isMaster ? "[MASTER] " : ""}${s.type} - ${s.url.substring(0, 50)}...`;
        selectStreamChoice.appendChild(opt);
      });

      selectStreamChoice.addEventListener("change", () => {
        const selected = streams.find((s) => s.url === selectStreamChoice.value);
        if (selected) {
          currentStreamUrl = selected.url;
          streamTypeBadge.textContent = selected.isMaster ? "⭐ Master Playlist" : selected.type;
          streamUrlText.textContent = selected.url;
        }
      });
    }
  }

  // Download Stream Action
  btnDownloadStream.addEventListener("click", async () => {
    if (!currentStreamUrl) return;

    btnDownloadStream.disabled = true;
    btnDownloadStreamLabel.textContent = "Queuing...";

    try {
      const isOnline = await checkServer();
      if (!isOnline) {
        showBanner("Local server is offline! Start run_server.bat", "error");
        btnDownloadStream.disabled = false;
        btnDownloadStreamLabel.textContent = "Download Stream";
        return;
      }

      const payload = {
        url: currentStreamUrl,
        title: activeTab ? activeTab.title : undefined,
        referer: activeTab ? activeTab.url : undefined,
        quality: selectQuality.value,
        format: selectFormat.value,
      };

      chrome.runtime.sendMessage({ action: "SEND_DOWNLOAD", payload }, (res) => {
        btnDownloadStream.disabled = false;
        btnDownloadStreamLabel.textContent = "Download Stream";

        if (res && res.success) {
          showBanner(`Queued: ${res.task.title || "Video"} (${res.task.status})`, "success");
        } else {
          showBanner(res?.error || "Failed to queue download", "error");
        }
      });
    } catch (err) {
      btnDownloadStream.disabled = false;
      btnDownloadStreamLabel.textContent = "Download Stream";
      showBanner(err.message, "error");
    }
  });

  // Download Page URL Action (Direct yt-dlp page extractor)
  btnDownloadPage.addEventListener("click", async () => {
    if (!activeTab || !activeTab.url) return;

    try {
      const isOnline = await checkServer();
      if (!isOnline) {
        showBanner("Local server is offline! Start run_server.bat", "error");
        return;
      }

      const payload = {
        url: activeTab.url,
        title: activeTab.title,
        referer: activeTab.url,
        quality: selectQuality.value,
        format: selectFormat.value,
      };

      chrome.runtime.sendMessage({ action: "SEND_DOWNLOAD", payload }, (res) => {
        if (res && res.success) {
          showBanner(`Queued page: ${res.task.title || "Video"}`, "success");
        } else {
          showBanner(res?.error || "Failed to queue page URL", "error");
        }
      });
    } catch (err) {
      showBanner(err.message, "error");
    }
  });

  // Link to Web UI Dashboard
  linkDashboard.addEventListener("click", (e) => {
    e.preventDefault();
    chrome.tabs.create({ url: SERVER_URL });
  });
});
