// Content script to detect HTML5 video sources rendered in the DOM
(function () {
  function checkMediaElements() {
    const videos = document.querySelectorAll("video");
    videos.forEach((video) => {
      if (video.src && video.src.startsWith("http")) {
        chrome.runtime.sendMessage({
          action: "REGISTER_DOM_MEDIA",
          url: video.src
        }).catch(() => {});
      }

      const sources = video.querySelectorAll("source");
      sources.forEach((source) => {
        if (source.src && source.src.startsWith("http")) {
          chrome.runtime.sendMessage({
            action: "REGISTER_DOM_MEDIA",
            url: source.src
          }).catch(() => {});
        }
      });
    });
  }

  // Run on page load
  checkMediaElements();

  // Also observe dynamic DOM mutations for video players loaded asynchronously
  const observer = new MutationObserver(() => {
    checkMediaElements();
  });

  observer.observe(document.body || document.documentElement, {
    childList: true,
    subtree: true
  });
})();
