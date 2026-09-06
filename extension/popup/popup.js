document.addEventListener("DOMContentLoaded", async () => {
  // DOM Elements
  const serverStatus = document.getElementById("server-status");
  const serverStatusText = document.getElementById("server-status-text");
  const pageTitle = document.getElementById("page-title");
  const pageUrl = document.getElementById("page-url");

  const streamTypeBadge = document.getElementById("stream-type-badge");
  const streamFilename = document.getElementById("stream-filename");
  const streamProviderBadge = document.getElementById("stream-provider-badge");
  const streamUrlText = document.getElementById("stream-url-text");
  const btnCopyUrl = document.getElementById("btn-copy-url");
  const groupOtherStreams = document.getElementById("group-other-streams");
  const selectStreamChoice = document.getElementById("select-stream-choice");

  const inputVideoTitle = document.getElementById("input-video-title");
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
  let configuredProviders = [];

  // Load cached providers from storage if available
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["cachedProviders"], (res) => {
      if (res && Array.isArray(res.cachedProviders) && res.cachedProviders.length > 0) {
        configuredProviders = res.cachedProviders;
        if (detectedStreams.length > 0) {
          setupStreamSelection(detectedStreams);
        }
      }
    });
  }

  // Banner display helper
  function showBanner(text, type = "success") {
    messageBanner.className = `message-banner ${type}`;
    messageBanner.textContent = text;
    setTimeout(() => {
      messageBanner.className = "message-banner";
    }, 4500);
  }

  // Copy Stream URL
  if (btnCopyUrl) {
    btnCopyUrl.addEventListener("click", () => {
      if (currentStreamUrl) {
        navigator.clipboard.writeText(currentStreamUrl);
        showBanner("Stream URL copied to clipboard!", "success");
      }
    });
  }

  // Check Server Health & Load Settings
  async function checkServer() {
    const serverUrl = await getServerUrl();
    try {
      const res = await fetch(`${serverUrl}/api/status`, { signal: AbortSignal.timeout(2000) });
      if (res.ok) {
        const data = await res.json();
        serverStatus.className = "server-status online";
        serverStatusText.textContent = `Online (${data.active_count} active)`;

        try {
          const sRes = await fetch(`${serverUrl}/api/settings`, { signal: AbortSignal.timeout(2000) });
          if (sRes.ok) {
            const sData = await sRes.json();
            if (sData?.settings?.providers && Array.isArray(sData.settings.providers)) {
              configuredProviders = sData.settings.providers;
              if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
                chrome.storage.local.set({ cachedProviders: configuredProviders });
              }
              if (detectedStreams.length > 0) {
                setupStreamSelection(detectedStreams);
              }
            }
          }
        } catch (_) {}

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
    pageTitle.title = activeTab.title || "";
    pageUrl.textContent = activeTab.url || "";
    pageUrl.title = activeTab.url || "";

    if (activeTab.title && inputVideoTitle) {
      inputVideoTitle.value = cleanVideoTitle(activeTab.title);
    }
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
          streamFilename.textContent = "No stream";
          streamUrlText.textContent = "No stream captured yet. Play video on the page or use 'Download Page URL'.";
          btnDownloadStream.disabled = true;
        }
      }
    );
  }

  function setupStreamSelection(streams) {
    btnDownloadStream.disabled = false;

    function applyStream(stream) {
      currentStreamUrl = stream.url;
      streamTypeBadge.textContent = stream.isMaster ? "⭐ Master Playlist" : stream.type;
      streamFilename.textContent = extractFilename(stream.url);
      const provider = detectProvider(stream.url, stream.referer, configuredProviders);
      if (provider && streamProviderBadge) {
        streamProviderBadge.textContent = provider;
        streamProviderBadge.style.display = "inline-block";
      } else if (streamProviderBadge) {
        streamProviderBadge.style.display = "none";
      }
      streamUrlText.textContent = stream.url;
      streamUrlText.title = stream.url;
    }

    applyStream(streams[0]);

    if (streams.length > 1) {
      groupOtherStreams.style.display = "flex";
      selectStreamChoice.innerHTML = "";
      streams.forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s.url;
        opt.textContent = formatStreamLabel(s, configuredProviders);
        opt.title = s.url;
        selectStreamChoice.appendChild(opt);
      });

      selectStreamChoice.value = streams[0].url;
      selectStreamChoice.title = streams[0].url;

      selectStreamChoice.onchange = () => {
        const selected = streams.find((s) => s.url === selectStreamChoice.value);
        if (selected) {
          applyStream(selected);
          selectStreamChoice.title = selected.url;
        }
      };
    } else {
      groupOtherStreams.style.display = "none";
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

      const chosenTitle = (inputVideoTitle ? inputVideoTitle.value.trim() : "") || (activeTab ? activeTab.title : undefined);
      const selectedStream = detectedStreams.find((s) => s.url === currentStreamUrl);
      const streamReferer = selectedStream?.referer || (activeTab ? activeTab.url : undefined);

      const capturedHeaders = { ...(selectedStream?.headers || {}) };
      if (streamReferer && !capturedHeaders["Referer"] && !capturedHeaders["referer"]) {
        capturedHeaders["Referer"] = streamReferer;
      }
      if (!capturedHeaders["User-Agent"] && !capturedHeaders["user-agent"] && typeof navigator !== "undefined" && navigator.userAgent) {
        capturedHeaders["User-Agent"] = navigator.userAgent;
      }
      const refForOrigin = capturedHeaders["Referer"] || capturedHeaders["referer"];
      if (refForOrigin && !capturedHeaders["Origin"] && !capturedHeaders["origin"]) {
        const derivedOrigin = deriveOriginFromReferer(refForOrigin);
        if (derivedOrigin) {
          capturedHeaders["Origin"] = derivedOrigin;
        }
      }

      const payload = {
        url: currentStreamUrl,
        title: chosenTitle,
        referer: streamReferer,
        headers: capturedHeaders,
        provider: detectProvider(currentStreamUrl, streamReferer, configuredProviders),
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

      const chosenTitle = (inputVideoTitle ? inputVideoTitle.value.trim() : "") || (activeTab ? activeTab.title : undefined);
      const headers = {};
      if (activeTab.url) {
        headers["Referer"] = activeTab.url;
        const derivedOrigin = deriveOriginFromReferer(activeTab.url);
        if (derivedOrigin) {
          headers["Origin"] = derivedOrigin;
        }
      }
      if (typeof navigator !== "undefined" && navigator.userAgent) {
        headers["User-Agent"] = navigator.userAgent;
      }

      const payload = {
        url: activeTab.url,
        title: chosenTitle,
        referer: activeTab.url,
        headers: headers,
        provider: detectProvider(activeTab.url, activeTab.url, configuredProviders),
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
  linkDashboard.addEventListener("click", async (e) => {
    e.preventDefault();
    const serverUrl = await getServerUrl();
    chrome.tabs.create({ url: serverUrl });
  });
});
