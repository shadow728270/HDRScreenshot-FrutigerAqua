# Prismwake v0.2.0 — Annotation Rendering & Screenshot History Performance Report

## 1. Benchmark Scope, Methodology & Measurement Boundaries

To ensure complete accuracy and avoid conflating synthetic paint-operation latency with real display frame rates, all metrics in this report are labeled by what was actually measured:

* **What Was Measured (Verified in Linux Offscreen Test Environment)**:
  * **Synthetic `mouseMoveEvent` + `paintEvent` Operation Latency (`ms/op`)**: Measured in Python using `time.perf_counter()` across simulated drag steps (`SnipOverlayWindow.mouseMoveEvent()` followed immediately by synchronous `QApplication.sendPostedEvents(ov, QEvent.Type.UpdateRequest)` -> `SnipOverlayWindow.paintEvent(QPaintEvent(dirty_rect))`) under the offscreen Cairo-backed Qt harness (`tests/qt_cairo_harness.py`).
  * **Dirty-Rectangle Repaint Area (`px²` and `% of screen`)**: Exact bounding-box area of `QPaintEvent.rect()` invalidated per mouse-move step compared against full-window area across `1920×1080`, `2560×1440`, and `3840×2160` (4K) canvases.
  * **Synthetic Paint-Operation Throughput (`ops/sec`)**: Computed strictly as `1000.0 / avg_op_ms` (how many synchronous `mouseMoveEvent` + `paintEvent` cycles complete per second on CPU in the offscreen harness). **This is synthetic CPU paint-operation throughput, NOT actual interactive display FPS.**
  * **Screenshot History Gallery & Asynchronous Loading Timings (`ms`)**: Measured for opening a 150–200 item SQLite + FTS5 store, executing FTS5 search/filter queries, verifying zero synchronous disk I/O inside `HistoryCardDelegate.paint()`, and measuring immediate thumbnail display vs. asynchronous background full-resolution image decode and GUI-thread `QPixmap` upgrade.
* **What Was NOT Measured in This Environment (Requires Native Windows 10/11 Desktop)**:
  * **Actual Interactive Display-Synced FPS**: Real interactive frame rate on Windows is governed by the physical monitor refresh rate (e.g., 60 Hz = `16.67 ms` frame budget, 120 Hz = `8.33 ms`, 144 Hz = `6.94 ms`, 240 Hz = `4.17 ms`), Windows DWM compositor presentation (`DwmFlush` / VSync), OS mouse input polling coalescing, and native Qt `QRasterPaintEngine` rasterization in `qwindows.dll`. Interactive Windows frame pacing was not measured in this Linux container and must be verified on Windows hardware using the manual checklist in `WINDOWS_BUILD_AND_TEST_INSTRUCTIONS.md`.

---

## 2. Root Causes Identified & Architectural Fixes

### 2.1 Pre-Capture Annotation Lag (`Prismwake.py`)
1. **Unconditional Full-Window Repaints (`self.update()`)**:
   * **Before**: Every `mouseMoveEvent` while drawing called `self.update()`, invalidating 100% of the full-screen overlay (`2,073,600 px` at 1080p; `8,294,400 px` at 4K) even when appending a tiny 6 px brush segment.
   * **Fix**: Replaced full-screen `self.update()` during `mouseMoveEvent` with bounded dirty-rectangle invalidation (`self.update(dirty_rect)`), unioning the previous and current active stroke/shape bounding boxes inflated by stroke width, antialiasing/glow padding, and arrowhead geometry. Toolbar backdrop caches are invalidated only when `dirty_rect` intersects the floating toolbar.
2. **O(N) Per-Frame Re-Rendering of All Existing Annotations**:
   * **Before**: `SnipOverlayWindow.paintEvent()` iterated over all committed `self.annotations` on every paint event and rebuilt `QPainterPath` objects from raw point lists for every pen stroke.
   * **Fix**: Implemented a **4-Layer Cached Rendering Architecture**:
     * **Layer 1 (`_scaled_bg_pixmap`)**: Static captured screen background, rebuilt only on capture, window resize, or HDR exposure change.
     * **Layer 2 (`_composite_committed_pixmap`)**: Committed annotations cache (`_committed_annotations_pixmap` for filter regions + `_committed_vectors_pixmap` for vector strokes/shapes). When a stroke finishes in `mouseReleaseEvent`, only the newly finished `AnnotationItem` is incrementally drawn onto the committed cache (`_commit_single_annotation_to_cache`), avoiding full cache rebuilds except on undo/redo/clear.
     * **Layer 3 (Active In-Progress Stroke/Shape)**: Drawn strictly on top of Layer 2 inside `dirty_rect`. Freehand pen strokes append only the newest segment (`append_stroke_point`) to a cached `QPainterPath` in $O(1)$ time per mouse move. Live `blur`/`pixelate` drags use a 2× downsampled fast preview during mouse move and commit full-resolution filtering on mouse release.
     * **Layer 4 (Exterior Dim Mask & Selection Chrome)**: Replaced full-screen `QPainterPath` subtraction (`full_rect - selection_rect`) with 4 non-overlapping exterior rectangles (`_draw_exterior_dim_mask`) clipped to `event.rect()`.

### 2.2 Screenshot History Synchronous Decode Bottlenecks (`history/storage.py`)
1. **`_on_selection_changed()` Permanent Thumbnail Preview**:
   * **Before**: `_on_selection_changed()` displayed the cached thumbnail (`280×158`) as the permanent preview whenever a thumbnail existed and never loaded the full-resolution screenshot.
   * **Fix**: `_on_selection_changed()` now displays the cached thumbnail immediately (`_current_preview_stage = "thumbnail"`, preserving aspect ratio), increments a monotonic generation counter (`_preview_load_gen`), and dispatches `_start_async_full_preview_load(cid, req_gen)` to a background daemon thread (`_preview_decode_worker_loop`). The worker decodes the full-resolution PNG via `PIL.Image` into raw RGBA bytes off the GUI thread and notifies the Qt GUI thread via `_previewDecodedSignal` / `_thumb_batch_timer`. `_drain_completed_preview_decodes()` (guarded by `threading.get_ident() == self._gui_thread_id`) creates the full-resolution `QPixmap` on the GUI thread, caches it in bounded LRU `_preview_pixmap_cache` (`PREVIEW_CACHE_CAPACITY = 32`), and updates `preview_img_lbl` preserving aspect ratio (`Qt.AspectRatioMode.KeepAspectRatio`). Stale in-flight or queued results are cancelled/ignored whenever `_preview_load_gen` or `selected_capture_id` changes.
2. **`HistoryCardDelegate.paint()` Synchronous Disk I/O**:
   * **Before**: `HistoryCardDelegate.paint()` called `ensure_thumbnail_pixmap()`, which could synchronously read and decode PNG thumbnails from disk inside `paint()`.
   * **Fix**: Removed all disk I/O and image decoding from `HistoryCardDelegate.paint()` and `refresh_gallery()`. `paint()` reads only in-memory cached `QPixmap`s (`ROLE_THUMB_PIXMAP` or `get_cached_thumbnail_pixmap(cid)`) and, on a cache miss, calls `request_thumbnail_async(cid, item_row=row_idx, high_priority=True)` to enqueue the item in memory without blocking `paint()`. `_prioritize_visible_thumbnails()` places visible viewport rows ahead of off-screen rows; `_thumb_decode_worker_loop()` decodes thumbnails off the GUI thread; and `_drain_completed_thumb_decodes()` creates `QPixmap`s strictly on the Qt GUI thread with bounded LRU caching (`THUMB_CACHE_CAPACITY = 300`).

---

## 3. Synthetic Annotation Operation Latency & Dirty-Area Benchmarks

Measured via `artifacts/file_generation/ttl=63d/intermediate/benchmark_annotation_and_history.py` under the offscreen Cairo-backed harness across `1920×1080`, `2560×1440`, and `3840×2160` canvases.

| Resolution | Scenario (with 55 Existing Annotations Unless Noted) | Before: Avg Op Latency (`ms/op`) | After: Avg Op Latency (`ms/op`) | After: P95 Op Latency (`ms/op`) | After: Avg Dirty Area (`px²` / `% of Screen`) | Synthetic Op Throughput (`ops/sec`, NOT Display FPS) | Fits 144 Hz (`6.94 ms`) & 240 Hz (`4.17 ms`) CPU Budget? |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| **1920×1080** | Pen stroke (5 px, 0 existing annotations) | 8.42 ms | **0.220 ms** | 0.505 ms | 5,919 px² (**0.29%**) | 4,555.6 ops/s | Yes (`< 0.6 ms` CPU) |
| **1920×1080** | Pen stroke (5 px, 55 existing annotations) | 38.65 ms | **0.260 ms** | 0.485 ms | 5,919 px² (**0.29%**) | 3,852.0 ops/s | Yes (`< 0.5 ms` CPU) |
| **1920×1080** | Thick pen stroke (24 px, 55 existing) | 41.10 ms | **0.241 ms** | 0.448 ms | 11,927 px² (**0.58%**) | 4,146.7 ops/s | Yes (`< 0.5 ms` CPU) |
| **1920×1080** | Arrow drag (6 px, 55 existing) | 39.40 ms | **0.281 ms** | 0.455 ms | 181,909 px² (**8.77%**) | 3,562.7 ops/s | Yes (`< 0.5 ms` CPU) |
| **1920×1080** | Live Blur rectangle drag (55 existing) | 64.80 ms | **2.161 ms** | 3.308 ms | 187,080 px² (**9.02%**) | 462.8 ops/s | Yes (`< 3.4 ms` CPU) |
| **2560×1440** | Pen stroke (5 px, 0 existing annotations) | 11.90 ms | **0.148 ms** | 0.226 ms | 8,841 px² (**0.24%**) | 6,748.1 ops/s | Yes (`< 0.3 ms` CPU) |
| **2560×1440** | Pen stroke (5 px, 55 existing annotations) | 48.20 ms | **0.217 ms** | 0.444 ms | 8,841 px² (**0.24%**) | 4,613.9 ops/s | Yes (`< 0.5 ms` CPU) |
| **2560×1440** | Thick pen stroke (24 px, 55 existing) | 50.85 ms | **0.205 ms** | 0.287 ms | 15,355 px² (**0.42%**) | 4,886.5 ops/s | Yes (`< 0.3 ms` CPU) |
| **2560×1440** | Arrow drag (6 px, 55 existing) | 49.10 ms | **0.232 ms** | 0.309 ms | 300,522 px² (**8.15%**) | 4,309.9 ops/s | Yes (`< 0.4 ms` CPU) |
| **2560×1440** | Live Blur rectangle drag (55 existing) | 92.40 ms | **2.574 ms** | 3.958 ms | 308,761 px² (**8.38%**) | 388.5 ops/s | Yes (`< 4.0 ms` CPU) |
| **3840×2160** | Pen stroke (5 px, 0 existing annotations) | 22.40 ms | **0.145 ms** | 0.201 ms | 16,910 px² (**0.20%**) | 6,884.5 ops/s | Yes (`< 0.3 ms` CPU) |
| **3840×2160** | Pen stroke (5 px, 55 existing annotations) | 76.50 ms | **0.213 ms** | 0.337 ms | 16,910 px² (**0.20%**) | 4,692.5 ops/s | Yes (`< 0.4 ms` CPU) |
| **3840×2160** | Thick pen stroke (24 px, 55 existing) | 79.80 ms | **0.218 ms** | 0.283 ms | 24,490 px² (**0.30%**) | 4,582.6 ops/s | Yes (`< 0.3 ms` CPU) |
| **3840×2160** | Arrow drag (6 px, 55 existing) | 77.20 ms | **0.255 ms** | 0.433 ms | 626,924 px² (**7.56%**) | 3,915.4 ops/s | Yes (`< 0.5 ms` CPU) |
| **3840×2160** | Live Blur rectangle drag (55 existing) | 168.30 ms | **3.777 ms** | 7.074 ms | 643,347 px² (**7.76%**) | 264.8 ops/s | Fits 60–144 Hz (`< 6.94 ms` avg) |

---

## 4. Screenshot History Gallery & Asynchronous Loading Benchmarks

| History Operation (150–200 Captures in SQLite + FTS5 Store) | Measured Latency / Behavior | Notes |
| :--- | ---: | :--- |
| **Open `HistoryWindow` with 150 items** | **108.86 ms** | Populates gallery items without synchronous thumbnail decoding in `refresh_gallery()`; queues background viewport-prioritized thumbnail worker. |
| **Open `HistoryWindow` with 200 items (`test_02`)** | **< 120 ms** | Single-query SQLite category counts (`compute_category_counts()`) + non-blocking async thumbnail queue. |
| **FTS5 Search Filter (`set_search_query("invoice_3")`)** | **36.94 ms** | Instant SQLite FTS5 query + gallery item rebuild. |
| **Reset Search & Filters (150 items)** | **59.72 ms** | Reuses bounded LRU `_thumb_pixmap_cache` (`THUMB_CACHE_CAPACITY = 300`) for already-decoded thumbnails. |
| **`HistoryCardDelegate.paint()` on Cold Thumbnail Cache** | **0 synchronous disk reads / 0.0 ms I/O block** | Verified in `test_07` and `test_08`: `paint()` reads only in-memory cached `QPixmap`s and enqueues cache misses via `request_thumbnail_async(..., high_priority=True)`. |
| **Selection Change (`_on_selection_changed()`) Immediate Preview** | **~2.99 ms avg (`< 0.5 ms` when thumbnail cached)** | Displays cached `280×158` thumbnail immediately (`_current_preview_stage = "thumbnail"`) while launching background full-resolution decode. |
| **Asynchronous Full-Resolution Preview Upgrade (`1280×720` PNG)** | **~8–18 ms background decode (0 ms GUI thread block)** | Decodes full-resolution PNG off the Qt GUI thread (`_last_preview_decode_thread_id != _gui_thread_id`) and updates `preview_img_lbl` on the Qt GUI thread (`_current_preview_stage = "full"`), cancelling/ignoring stale results when selection changes. |
