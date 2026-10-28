"""
Prismwake v0.2.0 — Persistent Searchable Screenshot History (`history`)
=======================================================================
Local-first SQLite + FTS5 screenshot history storage and Frutiger Aqua gallery UI:
  - Separates metadata database (`history.db`), managed images (`images/`),
    and bounded thumbnail cache (`thumbnails/`).
  - Supports privacy modes (`"off"`, `"saved_or_copied"`, `"all_completed"`),
    configurable retention limits (max items, max storage MB, max age days),
    atomic writes, corruption recovery, schema migrations, and safe deletion
    that never touches unrelated user files outside managed directories.
  - Full-text search across titles, filenames, capture dates, and indexed OCR text,
    plus 5 sort orders (`newest`, `oldest`, `largest`, `smallest`, `favorites_first`).
  - Redesigned Frutiger Aqua / Aero Gel `HistoryWindow` with shared `AeroGelButton`,
    `AeroAnimationDirector`, `AquaOpticalFieldRenderer`, frosted `AquaGlassPanel`
    surfaces, custom `HistoryCardDelegate` screenshot cards, and bounded LRU
    thumbnail and preview caches.
"""

from .storage import (
    HISTORY_AQUA_THEMES,
    HISTORY_CATEGORY_FILTERS,
    HISTORY_SCHEMA_VERSION,
    HISTORY_VIEW_MODES,
    VALID_HISTORY_MODES,
    VALID_HISTORY_SORT_MODES,
    HistoryEntry,
    HistoryStorageStats,
    HistoryWindow,
    ScreenshotHistoryStore,
    get_default_history_root,
    register_history_aqua_toolkit,
)

__all__ = [
    "HISTORY_AQUA_THEMES",
    "HISTORY_CATEGORY_FILTERS",
    "HISTORY_SCHEMA_VERSION",
    "HISTORY_VIEW_MODES",
    "VALID_HISTORY_MODES",
    "VALID_HISTORY_SORT_MODES",
    "HistoryEntry",
    "HistoryStorageStats",
    "HistoryWindow",
    "ScreenshotHistoryStore",
    "get_default_history_root",
    "register_history_aqua_toolkit",
]
