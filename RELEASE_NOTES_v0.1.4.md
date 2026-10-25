# Prismwake v0.1.4 · The Polish Update

**Prismwake v0.1.4** focuses on settings usability, native Windows branding, and reliable capture/editing operations.

## Changes
- Responsive and resizable Frutiger Aqua settings window, with saved dimensions, on-screen clamping, readable short dropdown labels and accessible tooltips.
- Multi-resolution Prismwake Windows icon and bundled runtime icons for tray, application windows and dialogs.
- Windows executable FileVersionInfo metadata and icon-aware GitHub Actions packaging.
- Clipboard copy improvements, annotation/rendering regression coverage, and performance/resource cleanup.
- Existing HDR capture pipeline, redaction, blur, pixelation, Paint Bucket and numbered callouts retained.

## Windows downloads
- **Prismwake.exe**: primary standalone Windows x64 program.
- **HDRSnipFusion.exe**: byte-identical legacy updater alias so older v0.1.2 and v0.1.3 clients can automatically upgrade.
- Each executable has its own SHA-256 verification sidecar. Both executable files must have the same hash.

## Technical compatibility
The original repository URL `shadow728270/HDRScreenshot-FrutigerAqua` is intentionally retained as the updater channel. Existing screenshot directories, update helpers, settings and startup identifiers are preserved. Neither executable is digitally signed, so Windows may show a SmartScreen notice.

## Validation
The accompanying headless test suites cover settings sizing, profile persistence, icon frames, PE version metadata, clipboard/annotation behavior and update parsing. The Windows workflow additionally verifies real packaged executables, checksum matching, startup, in-place executable replacement and rollback.

**Note:** Native HDR capture, system tray display and mixed-monitor DPI behavior depend on the user's Windows environment.
