# 💧 Prismwake release archive · v0.1.2
_Archived v0.1.2 release, originally distributed under the previous app name. The executable and internal updater identifiers are unchanged._

### More control over every pixel.

> **New:** adjustable stroke thickness, a non-destructive Paint Bucket, and refined annotation controls. HDR capture and the Frutiger Aqua interface remain intact.

![Original Aqua screenshot editor](https://raw.githubusercontent.com/shadow728270/HDRScreenshot-FrutigerAqua/main/docs/assets/hdrsnip-capture-overlay.webp)

*Earlier toolbar screenshot. The new v0.1.2 annotation controls aren't shown here.*

## 🖊️ Adjustable line thickness
- Visible 1–40 px control and live brush preview.
- Pen, rectangle, ellipse, line and arrow support adjustable thickness.
- Mouse-wheel and [ / ] keyboard adjustments.
- Existing annotations retain their originally selected thickness.
- Settings persist between capture sessions.

## 🪣 Non-destructive Paint Bucket
- Fill connected regions using the new **Fill (F)** tool.
- Adjust color tolerance and opacity.
- Fill masks are stored as undoable annotations rather than altering the original screenshot.
- Works with undo/redo, clipboard copy, and full-resolution save/export.

## ⌨️ Shortcuts

| Action | Shortcut |
|:--|:--|
| Capture (default) | **Ctrl+Shift+X** |
| Pen | **P** |
| Paint Bucket | **F** |
| Stroke thickness | **[** / **]** |
| Save to default folder | **Ctrl+S** |
| Quick Save and Copy | **Ctrl+Shift+S** |
| Save As | **Ctrl+Alt+S** |
| Undo / Redo | **Ctrl+Z** / **Ctrl+Y** |

## ⬇️ Download and update
Download **HDRSnipFusion.exe** from Assets below (Windows 10/11 x64; no Python required), or on v0.1.1 use **Settings → Application Updates → Check for Updates**.

This executable is unsigned; Windows SmartScreen may warn. The attached **HDRSnipFusion.exe.sha256** supports integrity verification.

> HDR capture uses DXGI and exports tone-mapped SDR images, not native HDR image files.

<details><summary><strong>Build and testing notes</strong></summary>

GitHub Actions verifies the 64-bit Windows executable, embedded application version, SHA-256, and its packaged updater behavior. Report tool, fill, or scaling issues in the [issue tracker](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/issues).

</details>

[🌊 Website](https://shadow728270.github.io/HDRScreenshot-FrutigerAqua/) · [Source](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua)
