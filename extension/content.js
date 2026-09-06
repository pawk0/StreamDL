// Content script to detect HTML5 video sources rendered in the DOM, including iframes
(function () {
  const registeredUrls = new Set();

  function registerMedia(url) {
    if (!url || typeof url !== "string" || !url.startsWith("http")) return;
    if (registeredUrls.has(url)) return;
    registeredUrls.add(url);

    try {
      const sendPromise = chrome.runtime.sendMessage({
        action: "REGISTER_DOM_MEDIA",
        url: url,
        referer: window.location.href,
        title: document.title || ""
      });
      if (sendPromise && typeof sendPromise.catch === "function") {
        sendPromise.catch(() => {});
      }
    } catch (e) {}
  }

  function checkMediaElements() {
    const videos = document.querySelectorAll("video");
    videos.forEach((video) => {
      if (video.src) registerMedia(video.src);
      if (video.currentSrc) registerMedia(video.currentSrc);

      const sources = video.querySelectorAll("source");
      sources.forEach((source) => {
        if (source.src) registerMedia(source.src);
      });
    });
  }

  // Intercept media play and load events
  window.addEventListener(
    "play",
    (e) => {
      if (e.target && (e.target.tagName === "VIDEO" || e.target.tagName === "AUDIO")) {
        if (e.target.currentSrc) registerMedia(e.target.currentSrc);
        if (e.target.src) registerMedia(e.target.src);
      }
    },
    true
  );

  window.addEventListener(
    "loadeddata",
    (e) => {
      if (e.target && (e.target.tagName === "VIDEO" || e.target.tagName === "AUDIO")) {
        if (e.target.currentSrc) registerMedia(e.target.currentSrc);
        if (e.target.src) registerMedia(e.target.src);
      }
    },
    true
  );

  // Initial check and observe DOM changes
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", checkMediaElements);
  } else {
    checkMediaElements();
  }

  const observer = new MutationObserver(() => {
    checkMediaElements();
  });

  observer.observe(document.documentElement || document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["src"]
  });
})();
