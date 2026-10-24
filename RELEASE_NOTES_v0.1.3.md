# Prismwake v0.1.3 · New identity, precision editor

**Official Windows release.** Validated with GitHub Actions x64 packaging, frozen v0.1.2 updater compatibility tests, candidate unit tests, and real staged replacement/startup/rollback tests.

### Highlights
- Desktop app rebranded as **Prismwake** with Ocean Current, Emerald Glass, Sunset Coral and Vista Sapphire.
- New blur, pixelation and opaque redaction tools with brush or rectangle modes.
- Numbered annotation callouts, pixel magnifier, eyedropper and refined annotation controls.
- Retains HDR-aware DXGI capture, non-destructive Paint Bucket and existing editing workflow.

### Existing-user updater compatibility
Both `Prismwake.exe` and **`HDRSnipFusion.exe` contain identical tested bytes**. The second name is intentional: previously installed v0.1.2 clients require that exact filename to auto-update safely. Both have SHA-256 sidecar files, and the original GitHub repository URL remains the updater endpoint. Existing executable paths and preferences are preserved.

### Known restrictions
The current capture export remains an HDR-aware **tone-mapped SDR PNG**, not a native HDR screenshot. Windows SmartScreen may warn because the executable is unsigned. Native Windows capture, multi-monitor, tray and clipboard behavior depend on the user's Windows hardware.
