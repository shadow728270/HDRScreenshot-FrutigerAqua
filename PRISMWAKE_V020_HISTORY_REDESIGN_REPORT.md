# Prismwake v0.2.0 — Frutiger Aqua Screenshot History Redesign & Asynchronous Pipeline Report

## 1. Visual Architecture & Shared Frutiger Aqua Design System

`HistoryWindow` in `history/storage.py` shares the main application's Frutiger Aqua visual engine without circular imports via `register_history_aqua_toolkit()` and `_resolve_prismwake_toolkit()`:

* **Shared Components Reused from `Prismwake.py`**:
  * `AeroGelButton`: Used for all header, sidebar, empty-state, and inspector actions (`sapphire`, `emerald`, `glass`, and destructive `ruby` variants), providing smooth 240 ms hover transitions, inward silicone-gel press compression, elastic release rebound, moving specular highlights, and localized click water ripples.
  * `AeroAnimationDirector`: Synchronizes `HistoryWindow` and all child `AeroGelButton` instances to the shared ~30 FPS animation clock. Automatically pauses when `HistoryWindow` is hidden, minimized, closed, or when Animation Intensity is set to `Off` / Safe Mode.
  * `AquaOpticalFieldRenderer`, `draw_frutiger_glass_base`, `draw_frutiger_glass_Dynamic_Overlay`, and `draw_frutiger_glass_panel`: Render the layered translucent aqua-blue glass backdrop (`_cached_base_pix`), bounded low-resolution (`176×56`) optical water caustics (`_cached_water_frame`), and frosted `AquaGlassPanel` sub-containers.
  * Live Theme & Transparency Synchronization: `HistoryWindow.apply_aqua_theme_and_config()` synchronizes live with all 5 Prismwake Aqua themes (`Bondi Blue` / `ocean_current`, `Emerald Lagoon` / `emerald_lagoon`, `Aurora Mint` / `aurora_mint`, `Sapphire Zenith` / `sapphire_zenith`, `Crystal Frost` / `crystal_frost`), glass transparency, and animation intensity.

---

## 2. Three-Region Gallery Layout & Top Header Bar

1. **Top Header Bar (`header_panel`)**:
   * Application title (`✦ Prismwake History`) and live capture/favorite count pill badge (`header_count_badge`).
   * Instant debounced search bar (`search_edit`, `Ctrl+F`) with one-click clear button (`clear_search_btn`).
   * 5-mode sort selector (`sort_combo`: `Newest First`, `Oldest First`, `Largest File`, `Smallest File`, `Favorites First`).
   * Checkable `⊞ Grid` (`view_grid_btn`) and `☰ List` (`view_list_btn`) view toggle buttons.
   * `✦ New Capture` (`new_capture_btn`, `emerald` gel) and `Storage & Privacy Settings` (`settings_btn`, `glass` gel).
2. **Left Filter & Storage Sidebar (`sidebar_panel`)**:
   * Checkable Frutiger Aqua category filter pills (`All Captures`, `★ Favorites`, `Recent (7 Days)`, `Recognized Text`) displaying live item counts from a single SQLite aggregation query (`compute_category_counts()`).
   * Structured **Storage & Privacy** card (`storage_card`) with privacy mode badge (`privacy_badge_lbl`), animated liquid usage bar (`AquaStorageMeterBar`), and item/OCR/megabyte breakdown.
   * Visually separated **History Cleanup** section (`Delete Selected`, `Clear Non-Favorites`, `Clear History...`).
3. **Center Screenshot Gallery (`gallery_panel`)**:
   * `HistoryGalleryListWidget` with hover-row tracking paired with custom-painted `HistoryCardDelegate` supporting both Grid Card (`218×182`) and Compact List (`height=72`) modes.
   * Each card renders a translucent aqua glass body, upper specular reflection arc, hover lift (`-1.6 px`) with cyan aura, luminous double-rim selection border, dark recessed thumbnail well preserving screenshot aspect ratio, top-left `OCR` pill badge, and top-right gold `★` favorite badge.
   * Dedicated `empty_state_card` distinguishing an empty history library from a search/filter with no matching results (including a one-click `Reset Search & Filters` button).
4. **Right Preview & Actions Inspector (`preview_panel`)**:
   * Capture title header, recessed dark glass preview well (`preview_well` / `preview_img_lbl`), metadata pill (`meta_label`), read-only **Recognized Text (OCR)** glass card (`ocr_card` / `ocr_preview` with word count badge), and three logically grouped rows of `AeroGelButton` actions (`Pin`, `Reopen in Editor`, `Copy Image`; `★ Favorite`, `Copy Text`, `Save As...`; `Rename`, `Open Location`, `Delete`).

---

## 3. Asynchronous Full-Resolution Preview & Gallery Thumbnail Pipeline

### 3.1 Asynchronous Full-Resolution Preview Loading (`_on_selection_changed()`)
* **Immediate Thumbnail Display**: When selection changes (`_on_selection_changed()`), `HistoryWindow` increments `_preview_load_gen`, checks `_preview_pixmap_cache` first, and on a cache miss immediately displays the cached thumbnail (`280×158` for a 16:9 capture, `_current_preview_stage = "thumbnail"`, `_current_preview_is_thumbnail = True`) scaled with `Qt.AspectRatioMode.KeepAspectRatio`.
* **Off-GUI-Thread Full-Resolution Decode**: `_start_async_full_preview_load(cid, req_gen)` dispatches the request to `_preview_decode_worker_loop()` running on a daemon background thread. The worker loads and decodes the full-resolution PNG via `PIL.Image` into raw RGBA bytes off the Qt GUI thread (`_last_preview_decode_thread_id != _gui_thread_id`).
* **Cancellation & Stale-Result Rejection**: If the user selects another item while a decode is queued or in progress, `_preview_load_gen` advances. Both the background worker (before and after disk I/O) and `_drain_completed_preview_decodes()` on the GUI thread check `req_gen == self._preview_load_gen and self.selected_capture_id == cid`, cancelling or ignoring stale results (`_cancelled_preview_decode_count`, `_ignored_stale_preview_count`) so an older decode never overwrites a newer selection.
* **Safe GUI-Thread `QPixmap` Upgrade**: `_drain_completed_preview_decodes()` enforces `threading.get_ident() == self._gui_thread_id`, converts the RGBA buffer to a `QPixmap` on the Qt GUI thread, stores it in bounded LRU `_preview_pixmap_cache` (`PREVIEW_CACHE_CAPACITY = 32`), sets `_current_preview_stage = "full"` and `_current_preview_is_thumbnail = False`, and updates `preview_img_lbl` preserving aspect ratio.

### 3.2 Zero-I/O `HistoryCardDelegate.paint()` & Viewport-Prioritized Asynchronous Thumbnails
* **Zero Synchronous Disk I/O or Decoding in `paint()`**: `HistoryCardDelegate.paint()` reads only in-memory cached `QPixmap`s (`index.data(ROLE_THUMB_PIXMAP)` or `get_cached_thumbnail_pixmap(cid)`). If a thumbnail is not yet cached in memory, `paint()` calls `request_thumbnail_async(cid, item_row=row_idx, high_priority=True)` to enqueue the item in memory and renders the recessed placeholder well without touching disk or decoding images inside `paint()`.
* **Visible-Item Prioritization**: `_prioritize_visible_thumbnails()` inspects the visible viewport row range (`_get_visible_row_range()`, updated on scroll, resize, show, and `set_visible_row_range()`) and reorders `_pending_thumb_rows` so visible cards are decoded before off-screen cards.
* **Off-Thread Decode & Bounded GUI-Thread Cache**: `_thumb_decode_worker_loop()` decodes thumbnail files off the GUI thread into RGBA byte buffers, and `_drain_completed_thumb_decodes()` creates `QPixmap`s strictly on the Qt GUI thread (`_last_thumb_pixmap_thread_id == _gui_thread_id`), attaches them to `ROLE_THUMB_PIXMAP`, caches them in bounded LRU `_thumb_pixmap_cache` (`THUMB_CACHE_CAPACITY = 300`), and triggers targeted viewport repaints.
