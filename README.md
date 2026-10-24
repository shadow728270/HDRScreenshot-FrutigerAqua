<p align="center"><img src="docs/assets/prismwake-mark.svg" width="104" alt="Prismwake logo"></p>

<h1 align="center">PRISMWAKE</h1>
<p align="center"><strong>Catch the light. Keep the detail.</strong></p>
<p align="center">A free, open-source Windows screenshot utility with HDR-aware capture, annotation tools, and a wonderfully glossy Frutiger Aqua spirit.</p>

<p align="center">
  <a href="https://shadow728270.github.io/HDRScreenshot-FrutigerAqua/">🌊 Explore the website</a> ·
  <a href="https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/latest/download/HDRSnipFusion.exe">⬇ Download the Windows EXE</a> ·
  <a href="https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases">Releases</a> ·
  <a href="https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/issues">Issues</a>
</p>

> **Rebrand in progress:** Prismwake is the project's new website and documentation identity. The latest stable desktop release is still **v0.1.2**, distributed as `HDRSnipFusion.exe` and branded with its previous name internally. Keeping the existing binary name, API repository address and user data paths preserves compatibility with installations and update checking. A coordinated desktop-app rename will follow separately. Historical Git tags and releases remain unchanged.

## See it in action

<img src="docs/assets/hdrsnip-capture-overlay.webp" alt="Real Aqua screenshot editor captured before the Prismwake desktop rebrand" width="850">

<img src="docs/assets/hdrsnip-settings.webp" alt="Real legacy Aqua settings dialog; desktop rebrand forthcoming" width="370">

The screenshots above are real captures of the current Windows application, not mockups of a future UI.

## What the desktop app can do

- **HDR-aware region screenshots.** Uses DXGI Desktop Duplication to read scRGB framebuffer data and tone-map it for shareable SDR PNG exports. True HDR file exports aren't implemented yet.
- **Annotation tools.** Pen, rectangles, ellipses, lines, arrows, text, adjustable **1–40 px** stroke widths, and a non-destructive **Paint Bucket** (v0.1.2).
- **Capture workflow.** Move and resize the capture region, undo/redo annotations, copy to clipboard, save or quick-save to a configurable folder.
- **Desktop integration.** Configurable global capture hotkey, Windows tray icon, single-instance guard, optional start with Windows, per-monitor/DPI awareness and diagnostic logging.
- **Updater.** Optional GitHub Releases update checking with download verification, staged replacement and rollback safety.
- **Aqua interface.** Refraction-inspired glass styling, animation intensity and transparency controls.

**Known limits:** Actual fullscreen behavior depends on the game, driver and presentation mode. Borderless fullscreen is generally safer. The EXE is unsigned, so Windows SmartScreen may show a warning.

## Try the new website lab

The <a href="https://shadow728270.github.io/HDRScreenshot-FrutigerAqua/#playground">Prismwake Lab</a> contains four lightweight, browser-side experiences:

1. **HDR comparison:** drag the slider to explore a clearly labeled, illustrative overexposure effect. This is a simulation, not a measured HDR-versus-SDR comparison, and has no upload feature.
2. **Interactive editor demo:** select a region, draw closed shapes, fill those drawings without sampling the background photograph, choose a fill color, add labels, and undo. Annotations are clipped to the selection. This is a browser sandbox, not an in-browser screen-capture engine.
3. **Aqua theme preview:** try Ocean, Emerald, Coral, or Vista themes plus transparency and motion preferences. These are **concept previews**, not yet desktop app settings.
4. **Live release history and roadmap:** recent published releases load from the GitHub API where available. Upcoming ideas are labeled as ideas, not committed shipping dates.

The website intentionally avoids permanent canvas animations and expensive full-page blur effects.

## Installation

1. Download [the latest stable executable](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/latest/download/HDRSnipFusion.exe).
2. Run it on 64-bit Windows 10/11. No Python installation is required.
3. Find its tray icon and use **Ctrl + Shift + X** by default. A previously saved hotkey may override this.
4. Choose your screenshot folder under Settings. Save with **Ctrl+S**, quick-save and copy with **Ctrl+Shift+S**, or open Save As with **Ctrl+Alt+S**.

## Running from source

Python 3.10+ on Windows:

```powershell
py -m pip install -r requirements.txt
py HDRSnipFusion.py
```

Builds and release automation live in [`.github/workflows/`](.github/workflows/). The legacy Python entry-point and packaged EXE names are intentionally unchanged for v0.1.2.

## Upcoming v0.1.3 transition

The [Prismwake v0.1.3 migration contract](docs/PRISMWAKE_V013_MIGRATION.md) documents the non-breaking app rename and how existing v0.1.2 users must continue to receive verified updates through the legacy executable asset and repository. The [automated compatibility suite](tests/test_legacy_updater_contract.py) checks the actual v0.1.2 update parser against future dual-named releases. **v0.1.3 is not published yet.**

## Releases, security and contributing

Read [the current release notes](RELEASE_NOTES_v0.1.2.md), [contributing guidelines](CONTRIBUTING.md) and [security policy](SECURITY.md). Downloads should come from the official GitHub Releases page only. Inspect diagnostic logs before sharing them publicly; paths, window titles and screenshots can contain private information.

Prismwake is an independent project distributed under the [MIT License](LICENSE).
