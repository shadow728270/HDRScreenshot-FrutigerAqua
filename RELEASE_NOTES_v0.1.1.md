# 🌊 HDRSnip Fusion v0.1.1
### Your screenshots, your folder. Updates without the scavenger hunt.

> **What's new:** One-click screenshot saving, a configurable save folder, and built-in GitHub Release update checking.

<p align="center"><img alt="HDRSnip Fusion HDR screenshot selection overlay with translucent Frutiger Aqua annotation controls" src="https://raw.githubusercontent.com/shadow728270/HDRScreenshot-FrutigerAqua/main/docs/assets/hdrsnip-capture-overlay.webp" width="780"></p>

<sub>Original Aqua capture interface. The new v0.1.1 saving and update controls aren't shown in this earlier screenshot.</sub>

---

## ✨ What's new

### 📁 Save in one click
Choose a **Default Save Location** once under **Settings → Screenshot Saving** with **Browse…**. The green **Save** button now writes a uniquely named PNG directly to that folder, without another file dialog.

- **Ctrl+S** saves to your selected folder.
- **Ctrl+Shift+S** quick-saves and copies the screenshot.
- **Ctrl+Alt+S** opens **Save As** to choose a location or filename.
- Safer temporary-file writes and unique filenames reduce overwrites and incomplete exports.
- If saving fails, the editor stays open with the screenshot and annotations intact.

### 🔄 Check for updates in the app
Look under **Settings → Application Updates** for automatic update checks, an on-demand **Check for Updates** button, and update preferences.

- Checks the official **stable GitHub Releases** for newer versions.
- Validates the downloaded Windows EXE against its SHA-256 checksum before installation.
- Installs through a separate helper, with restart confirmation and rollback protection.
- **User confirmation is required to install.** No surprise restart in the middle of an annotation session.
- Automatic *checking* is on by default and can be disabled.

> **Updating from v0.1.0?** Download v0.1.1 manually once: v0.1.0 did not have the updater. If you participated in the temporary v0.1.2 update test, manually reinstall v0.1.1 because the updater does not downgrade versions.

### 🪸 Still HDR-aware. Still Aqua.
DXGI-based HDR and Auto HDR capture, scRGB-to-SDR tone mapping, region selection, annotations, custom hotkeys, mixed-DPI display support, and animated translucent Aqua controls are preserved.

<p align="center"><img alt="Translucent HDRSnip Fusion Frutiger Aqua settings interface" src="https://raw.githubusercontent.com/shadow728270/HDRScreenshot-FrutigerAqua/main/docs/assets/hdrsnip-settings.webp" width="395"></p>

<sub>Earlier Settings screenshot for a preview of the glass aesthetic. The new Screenshot Saving and Application Updates sections appear in v0.1.1.</sub>

---

## ⌨️ Keyboard shortcuts

| Action | Shortcut |
| :-- | :-- |
| Screen capture (default, customizable) | **Ctrl+Shift+X** |
| Save PNG to default folder | **Ctrl+S** |
| Quick-save and copy | **Ctrl+Shift+S** |
| Save As | **Ctrl+Alt+S** |
| Copy to clipboard | **Ctrl+C** / **Enter** |

## ⬇️ Install / upgrade

1. Download **`HDRSnipFusion.exe`** from **Assets** below.
2. Exit the existing HDRSnip Fusion instance from the Windows system tray.
3. Launch the new executable, then configure the default save folder in Settings.

**Windows 10/11, 64-bit. No separate installer or Python installation needed.** The EXE is currently unsigned, so Windows SmartScreen may warn. Only download from this official repository.

For integrity verification, the release also includes **`HDRSnipFusion.exe.sha256`**.

<details>
<summary><strong>🛠️ Technical notes and validation</strong></summary>

- GitHub Actions built the Windows executable and verified its internal version, PE64 headers, and SHA-256.
- An automated Windows test exercised an update between two real PyInstaller one-file EXEs, including startup confirmation and rollback.
- A temporary live GitHub Release test successfully updated a v0.1.1 installation on Windows.
- HDR input is converted into tone-mapped **SDR PNG output**. Native HDR image files aren't exported yet.

</details>

Found a problem or have an idea? [Report it on GitHub](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/issues). Thanks for trying HDRSnip Fusion. 💧
