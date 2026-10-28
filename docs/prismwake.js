/* Prismwake v0.2.0 — Interactive Website Demos & Live GitHub Release Coordinator */
(function () {
  "use strict";

  // 1. Interactive Pinned Screenshot Demo (Drag, Resize, Opacity, Close, Spawn 2nd Pin)
  const stage = document.getElementById("pin-demo-stage");
  const opacityRange = document.getElementById("pin-opacity-range");
  const opacityLabel = document.getElementById("pin-opacity-label");
  const spawnBtn = document.getElementById("spawn-second-pin-btn");
  const resetPinsBtn = document.getElementById("reset-pins-btn");

  let activeDragPin = null;
  let activeResizePin = null;
  let startX = 0;
  let startY = 0;
  let startLeft = 0;
  let startTop = 0;
  let startW = 0;
  let startH = 0;

  function bindPinEvents(pinEl) {
    if (!pinEl) return;
    pinEl.addEventListener("pointerdown", function (e) {
      const closeTarget = e.target.closest("[data-pin-close]");
      if (closeTarget) {
        pinEl.style.display = "none";
        return;
      }
      const resizeTarget = e.target.closest("[data-pin-resize]");
      startX = e.clientX;
      startY = e.clientY;
      startLeft = parseFloat(pinEl.style.left) || 20;
      startTop = parseFloat(pinEl.style.top) || 20;
      startW = pinEl.offsetWidth;
      startH = pinEl.offsetHeight;
      if (resizeTarget) {
        activeResizePin = pinEl;
      } else {
        activeDragPin = pinEl;
      }
      pinEl.setPointerCapture(e.pointerId);
    });
  }

  if (stage) {
    bindPinEvents(document.getElementById("demo-pin-1"));
    stage.addEventListener("pointermove", function (e) {
      if (activeDragPin) {
        const nx = Math.max(4, Math.min(stage.clientWidth - activeDragPin.offsetWidth - 4, startLeft + (e.clientX - startX)));
        const ny = Math.max(4, Math.min(stage.clientHeight - activeDragPin.offsetHeight - 4, startTop + (e.clientY - startY)));
        activeDragPin.style.left = nx + "px";
        activeDragPin.style.top = ny + "px";
      } else if (activeResizePin) {
        const aspect = 300 / 176;
        const nw = Math.max(180, Math.min(460, startW + (e.clientX - startX)));
        const nh = Math.round(nw / aspect);
        activeResizePin.style.width = nw + "px";
        activeResizePin.style.height = nh + "px";
        const zoomPct = Math.round((nw / 300) * 100);
        const pill = activeResizePin.querySelector(".pin-zoom-pill");
        if (pill) {
          pill.textContent = zoomPct + "% • Resized (Aspect Locked)";
        }
      }
    });
    window.addEventListener("pointerup", function () {
      activeDragPin = null;
      activeResizePin = null;
    });
  }

  if (opacityRange && stage) {
    opacityRange.addEventListener("input", function () {
      const val = parseInt(opacityRange.value, 10) || 100;
      if (opacityLabel) opacityLabel.textContent = val + "%";
      const pins = stage.querySelectorAll(".pin-window");
      pins.forEach(function (p) {
        p.style.opacity = (val / 100).toFixed(2);
      });
    });
  }

  if (spawnBtn && stage) {
    spawnBtn.addEventListener("click", function () {
      let pin2 = document.getElementById("demo-pin-2");
      if (!pin2) {
        pin2 = document.createElement("div");
        pin2.className = "pin-window";
        pin2.id = "demo-pin-2";
        pin2.innerHTML =
          '<div class="pin-hover-bar">' +
          '<span class="pin-zoom-pill">100% • Pin #2 (DisplayConfig Lookup)</span>' +
          '<button type="button" class="pin-close-btn" data-pin-close="demo-pin-2" title="Close Pin">✕</button>' +
          "</div>" +
          '<div class="pin-body"><div class="pin-code-card">' +
          '<div class="code-title">Per-Monitor DPI &amp; Nits</div>' +
          "<code>DISPLAY1: 280 nits (150% DPI)</code>" +
          "<code>DISPLAY2: 203 nits (100% DPI)</code>" +
          "</div></div>" +
          '<div class="pin-resize-handle" data-pin-resize="demo-pin-2" title="Drag to resize"></div>';
        stage.appendChild(pin2);
        bindPinEvents(pin2);
      }
      pin2.style.display = "flex";
      pin2.style.left = "355px";
      pin2.style.top = "42px";
      pin2.style.width = "300px";
      pin2.style.height = "176px";
    });
  }

  if (resetPinsBtn && stage) {
    resetPinsBtn.addEventListener("click", function () {
      const p1 = document.getElementById("demo-pin-1");
      if (p1) {
        p1.style.display = "flex";
        p1.style.left = "28px";
        p1.style.top = "24px";
        p1.style.width = "300px";
        p1.style.height = "176px";
        p1.style.opacity = "1";
      }
      const p2 = document.getElementById("demo-pin-2");
      if (p2) p2.style.display = "none";
      if (opacityRange) opacityRange.value = "100";
      if (opacityLabel) opacityLabel.textContent = "100%";
    });
  }

  // 2. Interactive OCR Demo (Precomputed UI Simulation)
  const runOcrBtn = document.getElementById("run-ocr-demo-btn");
  const copyOcrBtn = document.getElementById("copy-ocr-demo-btn");
  const ocrTextarea = document.getElementById("ocr-demo-textarea");
  const ocrStatus = document.getElementById("ocr-demo-status");

  const SAMPLE_OCR_TEXT = [
    "DXGI Capture Diagnostic",
    "Adapter: NVIDIA GeForce RTX 4080 (scRGB FP16)",
    "Monitor: \\\\.\\DISPLAY1 • 3840x2160 @ 240Hz",
    "SDR White Level: 280 nits (scale = 3.50)",
    "Status: Frame acquired in 4.2 ms"
  ].join("\n");

  if (runOcrBtn && ocrTextarea) {
    runOcrBtn.addEventListener("click", function () {
      ocrTextarea.value = SAMPLE_OCR_TEXT;
      if (ocrStatus) {
        ocrStatus.textContent = "27 words, 5 lines recognized • Dark-theme auto-inverted (Browser UI demonstration)";
      }
    });
  }

  if (copyOcrBtn && ocrTextarea) {
    copyOcrBtn.addEventListener("click", function () {
      if (!ocrTextarea.value) ocrTextarea.value = SAMPLE_OCR_TEXT;
      ocrTextarea.select();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(ocrTextarea.value);
      }
      if (ocrStatus) ocrStatus.textContent = "Copied recognized text to clipboard.";
    });
  }

  // 3. Interactive History Gallery Demo
  const DEMO_HISTORY_ITEMS = [
    {
      id: "pw_01",
      title: "Vulkan Swapchain Error Dialog",
      date: "2026-10-24 14:22",
      dims: "680×320 px • 48 KB",
      mode: "Window Capture",
      favorite: true,
      ocr: "VK_ERROR_OUT_OF_DATE_KHR: Swapchain surface resized on DISPLAY1 (3840x2160)"
    },
    {
      id: "pw_02",
      title: "Auto-HDR Tone Curve Comparison",
      date: "2026-10-24 11:05",
      dims: "2560×1440 px • 412 KB",
      mode: "Fullscreen Capture",
      favorite: true,
      ocr: "SDR White Level: 280 nits | Knee Start: 0.80 | Headroom: 6.0x"
    },
    {
      id: "pw_03",
      title: "Context Menu Tooltip Snip",
      date: "2026-10-23 19:40",
      dims: "420×190 px • 29 KB",
      mode: "Delayed Capture (3s)",
      favorite: false,
      ocr: "Pin to Screen (Ctrl+P) • Extract Text Offline (O) • Save As (Ctrl+Alt+S)"
    },
    {
      id: "pw_04",
      title: "Python Traceback Snippet",
      date: "2026-10-22 16:12",
      dims: "890×410 px • 74 KB",
      mode: "Text Capture (OCR)",
      favorite: false,
      ocr: "sqlite3.OperationalError: FTS5 virtual table indexed 142 captures in 3.1 ms"
    }
  ];

  const histGrid = document.getElementById("history-grid-container");
  const histSearch = document.getElementById("history-search-input");
  const histFavBtn = document.getElementById("history-fav-filter-btn");
  const prevTitle = document.getElementById("hist-prev-title");
  const prevMeta = document.getElementById("hist-prev-meta");
  const prevOcr = document.getElementById("hist-prev-ocr");

  let favOnly = false;
  let selectedId = DEMO_HISTORY_ITEMS[0].id;

  function renderHistoryDemo() {
    if (!histGrid) return;
    const q = ((histSearch && histSearch.value) || "").trim().toLowerCase();
    const filtered = DEMO_HISTORY_ITEMS.filter(function (item) {
      if (favOnly && !item.favorite) return false;
      if (!q) return true;
      return (
        item.title.toLowerCase().indexOf(q) !== -1 ||
        item.date.toLowerCase().indexOf(q) !== -1 ||
        item.ocr.toLowerCase().indexOf(q) !== -1
      );
    });

    histGrid.innerHTML = "";
    filtered.forEach(function (item) {
      const card = document.createElement("div");
      card.className = "hist-thumb-card" + (item.id === selectedId ? " active" : "");
      card.innerHTML =
        "<div><strong>" + (item.favorite ? "★ " : "") + item.title + "</strong></div>" +
        '<div style="font-size:0.76rem;color:#9ed9f5;margin-top:4px;">' + item.date + " • " + item.dims + "</div>";
      card.addEventListener("click", function () {
        selectedId = item.id;
        renderHistoryDemo();
      });
      histGrid.appendChild(card);
    });

    const activeItem = filtered.find(function (i) { return i.id === selectedId; }) || filtered[0];
    if (activeItem) {
      if (prevTitle) prevTitle.textContent = (activeItem.favorite ? "★ " : "") + activeItem.title;
      if (prevMeta) prevMeta.textContent = activeItem.date + "  |  " + activeItem.dims + "  |  " + activeItem.mode;
      if (prevOcr) prevOcr.textContent = activeItem.ocr;
    } else {
      if (prevTitle) prevTitle.textContent = "No matching captures";
      if (prevMeta) prevMeta.textContent = "";
      if (prevOcr) prevOcr.textContent = "";
    }
  }

  if (histSearch) {
    histSearch.addEventListener("input", renderHistoryDemo);
  }
  if (histFavBtn) {
    histFavBtn.addEventListener("click", function () {
      favOnly = !favOnly;
      histFavBtn.setAttribute("data-fav-only", String(favOnly));
      histFavBtn.textContent = favOnly ? "★ Showing Favorites" : "★ Favorites Only";
      renderHistoryDemo();
    });
  }
  renderHistoryDemo();
})();
