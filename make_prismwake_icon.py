#!/usr/bin/env python3
"""
Prismwake v0.2.0 — Multi-Resolution Windows Icon, SVG Mark & PE Version Resource Generator
===========================================================================================
Deterministically generates:
  1. `prismwake-mark.svg` — Official scalable Frutiger Aqua vector identity mark
  2. `prismwake.ico`      — Genuine multi-resolution Windows `.ico` containing crisp,
                            size-optimized 32-bit RGBA PNG frames at:
                            16x16, 24x24, 32x32, 48x48, 64x64, 128x128, and 256x256
  3. `prismwake_version_info.txt` — PyInstaller Windows PE VSVersionInfo resource file
                                    declaring ProductName/FileDescription = "Prismwake"
                                    and FileVersion/ProductVersion = "0.2.0.0"

Design notes across icon resolutions:
  - Small sizes (16x16, 24x24, 32x32):
    Prioritizes silhouette clarity and high contrast for the Windows system tray,
    taskbar, Alt+Tab switcher, and Explorer small-icon views. Uses a bold luminous
    cyan-to-sapphire Aqua orb with a smooth, unified white/cyan "P" prism-wave monogram
    and crisp alpha anti-aliasing.
  - Medium & Large sizes (48x48, 64x64, 128x128, 256x256):
    Renders full Frutiger Aqua 3D liquid-glass depth: deep ocean sapphire-to-cyan
    sphere, subsurface emerald-mint bounce glow, rounded viewfinder frame, sculpted
    Prismwake "P" + refracted wave crest monogram, and glossy top specular reflection cap.
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
from typing import List, Sequence, Tuple

from PIL import Image, ImageDraw

ICON_SIZES: Tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

PRISMWAKE_SVG_CONTENT: str = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <defs>
    <radialGradient id="aquaSphere" cx="34%" cy="26%" r="72%">
      <stop offset="0%" stop-color="#E6FFFF" stop-opacity="1"/>
      <stop offset="28%" stop-color="#33E6FF" stop-opacity="1"/>
      <stop offset="68%" stop-color="#0078D7" stop-opacity="1"/>
      <stop offset="100%" stop-color="#002B66" stop-opacity="1"/>
    </radialGradient>
    <radialGradient id="emeraldBounce" cx="50%" cy="84%" r="48%">
      <stop offset="0%" stop-color="#69F0AE" stop-opacity="0.88"/>
      <stop offset="60%" stop-color="#00E5FF" stop-opacity="0.32"/>
      <stop offset="100%" stop-color="#00E5FF" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="specularCap" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.92"/>
      <stop offset="58%" stop-color="#E0FFFF" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="prismGlyph" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="1"/>
      <stop offset="55%" stop-color="#BDFBFF" stop-opacity="0.98"/>
      <stop offset="100%" stop-color="#69F0AE" stop-opacity="0.96"/>
    </linearGradient>
  </defs>
  <!-- Outer Frutiger Aqua Liquid Glass Orb -->
  <circle cx="128" cy="128" r="114" fill="url(#aquaSphere)" stroke="#D8FCFF" stroke-width="7"/>
  <!-- Subsurface Emerald-Aqua Bounce Glow -->
  <circle cx="128" cy="128" r="108" fill="url(#emeraldBounce)"/>
  <!-- Rounded Capture Viewfinder Frame -->
  <rect x="54" y="54" width="148" height="148" rx="34" ry="34"
        fill="none" stroke="#B8FAFF" stroke-width="6.5" stroke-opacity="0.72"/>
  <!-- Refracted Aqua Wave Ribbon -->
  <path d="M 64 166 C 92 146, 122 182, 154 156 C 172 142, 184 148, 194 140"
        fill="none" stroke="#69F0AE" stroke-width="11" stroke-linecap="round" opacity="0.92"/>
  <!-- Bold Prismwake 'P' + Prism Monogram -->
  <path d="M 92 180 L 92 78 L 138 78 C 164 78, 178 93, 178 114 C 178 135, 164 150, 138 150 L 92 150"
        fill="none" stroke="url(#prismGlyph)" stroke-width="20"
        stroke-linecap="round" stroke-linejoin="round"/>
  <polygon points="108,95 154,114 108,133" fill="#9EFFFF" opacity="0.92"/>
  <!-- Top Glossy Specular Reflection Cap -->
  <ellipse cx="128" cy="64" rx="76" ry="40" fill="url(#specularCap)"/>
</svg>
"""


def build_version_info_text(version_str: str = "0.2.0") -> str:
    """
    Generates a PyInstaller-compatible Windows VSVersionInfo specification file
    declaring Prismwake v0.2.0.0 metadata for File Explorer, Task Manager, and Properties.
    """
    parts = [int(p) for p in version_str.strip().lstrip("vV").split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    maj, min_v, pat = parts[0], parts[1], parts[2]
    ver_quad = f"{maj}.{min_v}.{pat}.0"
    return f"""# UTF-8
#
# Prismwake v{version_str} Windows PE Version Resource File (PyInstaller --version-file)
#
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({maj}, {min_v}, {pat}, 0),
    prodvers=({maj}, {min_v}, {pat}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'Prismwake Open Source Project'),
            StringStruct('FileDescription', 'Prismwake — HDR Screenshot & Annotation Tool'),
            StringStruct('FileVersion', '{ver_quad}'),
            StringStruct('InternalName', 'Prismwake'),
            StringStruct('LegalCopyright', 'Copyright (c) 2026 Prismwake Contributors (MIT License)'),
            StringStruct('OriginalFilename', 'Prismwake.exe'),
            StringStruct('ProductName', 'Prismwake'),
            StringStruct('ProductVersion', '{ver_quad}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def _build_p_outline_path(
    px_left: float,
    py_top: float,
    py_mid: float,
    py_bot: float,
    px_bowl: float,
    steps: int = 36,
) -> List[Tuple[float, float]]:
    """
    Builds a single smooth, continuous polyline for the Prismwake 'P' monogram:
      - Vertical stem from `(px_left, py_bot)` up to `(px_left, py_top)`
      - Top horizontal bar out to `x_arc_center`
      - Smooth semicircular loop around `(x_arc_center, y_arc_center)` with radius `r_arc`
      - Mid horizontal bar back to `(px_left, py_mid)`
    Drawing this as a single path with overlapping round discs at each vertex eliminates
    any step/notch artifacts between the straight bars and the semicircular bowl.
    """
    r_arc = (py_mid - py_top) * 0.5
    x_arc_center = max(px_left + r_arc * 0.35, px_bowl - r_arc)
    y_arc_center = (py_top + py_mid) * 0.5

    pts: List[Tuple[float, float]] = [
        (px_left, py_bot),
        (px_left, py_top),
        (x_arc_center, py_top),
    ]
    for i in range(1, steps):
        ang = -math.pi * 0.5 + (math.pi * i) / float(steps)
        pts.append(
            (
                x_arc_center + math.cos(ang) * r_arc,
                y_arc_center + math.sin(ang) * r_arc,
            )
        )
    pts.append((x_arc_center, py_mid))
    pts.append((px_left, py_mid))
    return pts


def _draw_thick_round_polyline(
    draw: ImageDraw.ImageDraw,
    pts: Sequence[Tuple[float, float]],
    color: Tuple[int, int, int, int],
    width: int,
) -> None:
    """Draws a smooth round-capped, round-joined thick polyline without corner notches."""
    if len(pts) < 2:
        return
    r = width * 0.5
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        seg_len = math.hypot(x1 - x0, y1 - y0)
        n_sub = max(2, int(math.ceil(seg_len / max(1.0, r * 0.28))))
        for j in range(n_sub + 1):
            u = j / float(n_sub)
            cx = x0 + (x1 - x0) * u
            cy = y0 + (y1 - y0) * u
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def render_prismwake_icon_frame(size: int) -> Image.Image:
    """
    Renders a single size-tuned RGBA frame for `size x size` using 4x supersampling
    so edges, specular highlights, and the Prismwake 'P' + prism wave silhouette
    remain razor-sharp at both 16x16/24x24 and 256x256.
    """
    scale = 4 if size <= 64 else 2
    canvas_sz = size * scale
    img = Image.new("RGBA", (canvas_sz, canvas_sz), (0, 0, 0, 0))
    px = img.load()

    cx = (canvas_sz - 1) * 0.5
    cy = (canvas_sz - 1) * 0.5
    margin = (1.0 if size <= 24 else 1.5) * scale
    radius = (canvas_sz * 0.5) - margin

    lx = canvas_sz * 0.34
    ly = canvas_sz * 0.25
    max_l_dist = radius * 1.65

    bx = canvas_sz * 0.50
    by = canvas_sz * 0.84
    max_b_dist = radius * 0.92

    aa_band = max(1.2, 1.15 * scale)

    for y in range(canvas_sz):
        dy = y - cy
        for x in range(canvas_sz):
            dx = x - cx
            dist = math.hypot(dx, dy)
            if dist > radius + aa_band:
                continue

            if dist <= radius - aa_band * 0.5:
                edge_alpha = 1.0
            else:
                edge_alpha = max(
                    0.0,
                    min(1.0, (radius + aa_band * 0.5 - dist) / aa_band),
                )
            if edge_alpha <= 0.0:
                continue

            u = min(1.0, math.hypot(x - lx, y - ly) / max_l_dist)
            if u < 0.28:
                t = u / 0.28
                r = 225.0 * (1.0 - t) + 28.0 * t
                g = 255.0 * (1.0 - t) + 224.0 * t
                b = 255.0 * (1.0 - t) + 255.0 * t
            elif u < 0.68:
                t = (u - 0.28) / 0.40
                r = 28.0 * (1.0 - t) + 0.0 * t
                g = 224.0 * (1.0 - t) + 114.0 * t
                b = 255.0 * (1.0 - t) + 212.0 * t
            else:
                t = (u - 0.68) / 0.32
                r = 0.0
                g = 114.0 * (1.0 - t) + 38.0 * t
                b = 212.0 * (1.0 - t) + 102.0 * t

            b_dist = math.hypot(x - bx, y - by)
            if b_dist < max_b_dist:
                bt = (1.0 - (b_dist / max_b_dist)) ** 1.7 * 0.62
                r = r * (1.0 - bt) + 95.0 * bt
                g = g * (1.0 - bt) + 252.0 * bt
                b = b * (1.0 - bt) + 195.0 * bt

            cap_dx = (x - cx) / (radius * 0.70)
            cap_dy = (y - (cy - radius * 0.52)) / (radius * 0.36)
            cap_r2 = cap_dx * cap_dx + cap_dy * cap_dy
            if cap_r2 < 1.0 and y < cy:
                vy = max(0.0, min(1.0, (cy - y) / (radius * 0.88)))
                cap_strength = ((1.0 - cap_r2) ** 0.75) * (vy ** 1.15) * 0.78
                r = r + (255.0 - r) * cap_strength
                g = g + (255.0 - g) * cap_strength
                b = b + (255.0 - b) * cap_strength

            rim_t = max(0.0, (dist - (radius - 2.2 * scale)) / (2.2 * scale))
            if rim_t > 0.0:
                rim_mix = (rim_t ** 1.4) * (0.74 if size <= 24 else 0.58)
                r = r + (228.0 - r) * rim_mix
                g = g + (254.0 - g) * rim_mix
                b = b + (255.0 - b) * rim_mix

            px[x, y] = (
                int(max(0, min(255, round(r)))),
                int(max(0, min(255, round(g)))),
                int(max(0, min(255, round(b)))),
                int(max(0, min(255, round(255.0 * edge_alpha)))),
            )

    draw = ImageDraw.Draw(img, "RGBA")

    # Medium/large sizes (>= 32px): subtle inner viewfinder rounded square
    if size >= 32:
        vf_inset = int(round(canvas_sz * 0.22))
        vf_radius = int(round(canvas_sz * 0.13))
        vf_width = max(2, int(round(canvas_sz * 0.025)))
        draw.rounded_rectangle(
            [vf_inset, vf_inset, canvas_sz - vf_inset, canvas_sz - vf_inset],
            radius=vf_radius,
            outline=(195, 252, 255, 160),
            width=vf_width,
        )

    # Refracted emerald-cyan wave ribbon under the 'P' monogram
    wave_pts: List[Tuple[float, float]] = []
    x_start = canvas_sz * (0.24 if size <= 24 else 0.26)
    x_end = canvas_sz * (0.78 if size <= 24 else 0.76)
    y_base = canvas_sz * (0.68 if size <= 24 else 0.65)
    amp = canvas_sz * (0.065 if size <= 24 else 0.055)
    steps = 32
    for i in range(steps + 1):
        u = i / float(steps)
        wx = x_start + (x_end - x_start) * u
        wy = y_base - math.sin(u * math.pi * 1.85) * amp
        wave_pts.append((wx, wy))
    wave_w = max(2, int(round(canvas_sz * (0.082 if size <= 24 else 0.060))))
    _draw_thick_round_polyline(draw, wave_pts, (105, 250, 190, 240), wave_w)

    # Sculpted Prismwake 'P' + prism facet monogram
    stroke_w = max(3, int(round(canvas_sz * (0.112 if size <= 24 else 0.084))))
    px_left = canvas_sz * (0.35 if size <= 24 else 0.36)
    py_top = canvas_sz * (0.26 if size <= 24 else 0.29)
    py_bot = canvas_sz * (0.74 if size <= 24 else 0.71)
    py_mid = canvas_sz * (0.53 if size <= 24 else 0.52)
    px_bowl = canvas_sz * (0.69 if size <= 24 else 0.67)

    p_path = _build_p_outline_path(px_left, py_top, py_mid, py_bot, px_bowl, steps=36)
    sh_off = max(1, int(round(canvas_sz * 0.018)))
    p_shadow = [(x + sh_off, y + sh_off) for (x, y) in p_path]
    _draw_thick_round_polyline(draw, p_shadow, (0, 30, 72, 195), stroke_w)

    # Inner cyan prism triangle inside the P loop
    tri_pts = [
        (px_left + stroke_w * 0.42, py_top + stroke_w * 0.52),
        (px_bowl - stroke_w * 0.48, (py_top + py_mid) * 0.5),
        (px_left + stroke_w * 0.42, py_mid - stroke_w * 0.52),
    ]
    draw.polygon(tri_pts, fill=(148, 255, 255, 228))

    # Smooth white-cyan 'P' monogram
    _draw_thick_round_polyline(draw, p_path, (255, 255, 255, 255), stroke_w)

    return img.resize((size, size), Image.Resampling.LANCZOS)


def write_multi_size_ico(
    ico_path: Path, sizes: Sequence[int] = ICON_SIZES
) -> List[Tuple[int, int]]:
    """
    Writes a genuine multi-resolution Windows `.ico` file containing explicit
    embedded PNG frames for every requested size (`16, 24, 32, 48, 64, 128, 256`).
    """
    import io

    ordered_sizes = [int(s) for s in sizes]
    png_payloads: List[bytes] = []
    dims: List[Tuple[int, int]] = []

    for sz in ordered_sizes:
        frame = render_prismwake_icon_frame(sz)
        buf = io.BytesIO()
        frame.save(buf, format="PNG", optimize=True)
        png_payloads.append(buf.getvalue())
        dims.append((sz, sz))

    count = len(ordered_sizes)
    header = struct.pack("<HHH", 0, 1, count)
    dir_entries = bytearray()
    data_offset = 6 + count * 16

    for (w, h), payload in zip(dims, png_payloads):
        b_w = 0 if w >= 256 else w
        b_h = 0 if h >= 256 else h
        entry = struct.pack(
            "<BBBBHHII",
            b_w,
            b_h,
            0,
            0,
            1,
            32,
            len(payload),
            data_offset,
        )
        dir_entries.extend(entry)
        data_offset += len(payload)

    ico_path = Path(ico_path)
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ico_path, "wb") as fh:
        fh.write(header)
        fh.write(dir_entries)
        for payload in png_payloads:
            fh.write(payload)

    return dims


def inspect_ico_frames(ico_path: Path) -> List[Tuple[int, int, int]]:
    """
    Parses the binary ICONDIR header of `ico_path` and returns a list of
    `(width, height, bit_count)` tuples for every embedded icon frame.
    """
    raw = Path(ico_path).read_bytes()
    if len(raw) < 6:
        raise ValueError(f"ICO file too small ({len(raw)} bytes): {ico_path}")
    reserved, ico_type, count = struct.unpack_from("<HHH", raw, 0)
    if reserved != 0 or ico_type != 1 or count <= 0:
        raise ValueError(
            f"Invalid ICO header (reserved={reserved}, type={ico_type}, count={count})"
        )
    frames: List[Tuple[int, int, int]] = []
    for idx in range(count):
        off = 6 + idx * 16
        b_w, b_h, _cc, _res, _planes, bpp, byte_len, img_off = struct.unpack_from(
            "<BBBBHHII", raw, off
        )
        w = 256 if b_w == 0 else int(b_w)
        h = 256 if b_h == 0 else int(b_h)
        if img_off + byte_len > len(raw) or byte_len <= 0:
            raise ValueError(f"Corrupt ICO frame #{idx} offset/size in {ico_path}")
        frames.append((w, h, int(bpp)))
    return frames


def generate_all_prismwake_assets(
    output_dir: Path, version_str: str = "0.2.0"
) -> dict:
    """
    Generates `prismwake-mark.svg`, `prismwake.ico`, and `prismwake_version_info.txt`
    inside `output_dir` (and mirrors `docs/assets/prismwake-mark.svg` if `docs/assets`
    exists nearby).
    """
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    svg_path = out / "prismwake-mark.svg"
    svg_path.write_text(PRISMWAKE_SVG_CONTENT, encoding="utf-8")

    docs_assets = out / "docs" / "assets"
    if docs_assets.exists() and docs_assets.is_dir():
        (docs_assets / "prismwake-mark.svg").write_text(
            PRISMWAKE_SVG_CONTENT, encoding="utf-8"
        )

    ico_path = out / "prismwake.ico"
    dims = write_multi_size_ico(ico_path, ICON_SIZES)

    ver_info_path = out / "prismwake_version_info.txt"
    ver_info_path.write_text(
        build_version_info_text(version_str), encoding="utf-8"
    )

    return {
        "svg_path": svg_path,
        "ico_path": ico_path,
        "version_info_path": ver_info_path,
        "ico_sizes": dims,
    }


if __name__ == "__main__":
    import sys

    target_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
    ver = sys.argv[2].strip() if len(sys.argv) > 2 else "0.2.0"
    result = generate_all_prismwake_assets(target_dir, version_str=ver)
    verified = inspect_ico_frames(result["ico_path"])
    print(
        f"[Prismwake Icon Generator] Wrote {result['ico_path'].name} with {len(verified)} frames: "
        f"{[f'{w}x{h}@{bpp}bpp' for w, h, bpp in verified]}"
    )
    print(f"[Prismwake Icon Generator] Wrote {result['svg_path'].name} and {result['version_info_path'].name}")