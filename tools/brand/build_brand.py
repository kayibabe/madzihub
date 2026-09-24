"""
tools/brand/build_brand.py — generate web brand assets from brand/source
=========================================================================
Masters live in brand/source (as delivered by design). This script derives
everything the app serves, so a brand refresh is: replace the masters, run

    python tools/brand/build_brand.py

and commit app/static/brand/*.  Requires fonttools, Pillow and a Chromium
binary (set CHROMIUM=/path/to/chrome if it is not auto-detected).

Why the text is outlined: the lockups name "DejaVu Sans", which is not
installed on Windows/macOS. Browsers would substitute Arial, the glyph widths
change, and "Madzi"/"Hub" (positioned absolutely) collide or drift apart.
Converting the text to paths makes the logo render identically everywhere.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import unescape

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "brand" / "source"
OUT = ROOT / "app" / "static" / "brand"
FONT_DIR = ROOT / "brand" / "fonts"

NAVY, TEAL, WHITE = "#142E49", "#16A9A8", "#FFFFFF"

# The mark, in its native 200x205 design space (taken from the masters).
DROP = "M100 7 C81 35 36 81 29 119 C19 165 51 198 100 198 C149 198 181 165 171 119 C164 81 119 35 100 7 Z"


def mark(ink: str, cls: str = "") -> str:
    """The drop + ledger line. `ink` colours the line/nodes; teal is fixed."""
    c = f' class="{cls}"' if cls else ""
    return (
        f'<path d="{DROP}" fill="none" stroke="{TEAL}" stroke-width="14" stroke-linejoin="round"/>'
        f'<path{c} d="M55 149 L91 117 L132 91" fill="none" stroke="{ink}" stroke-width="11" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle{c} cx="55" cy="149" r="12" fill="{ink}"/>'
        f'<circle cx="91" cy="117" r="12" fill="{TEAL}"/>'
        f'<circle{c} cx="132" cy="91" r="12" fill="{ink}"/>'
    )


# ── text → paths ─────────────────────────────────────────────────────────────
def _font(bold: bool) -> TTFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in (FONT_DIR, Path("/usr/share/fonts/truetype/dejavu")):
        if (d / name).exists():
            return TTFont(d / name)
    sys.exit(f"{name} not found; put it in {FONT_DIR}")


_FONTS: dict[bool, TTFont] = {}


def text_path(s: str, x: float, y: float, size: float, bold: bool, spacing: float) -> str:
    font = _FONTS.setdefault(bold, _font(bold))
    cmap, gs = font.getBestCmap(), font.getGlyphSet()
    hmtx, upm = font["hmtx"], font["head"].unitsPerEm
    scale = size / upm
    pen = SVGPathPen(gs)
    cx = x
    for ch in s:
        g = cmap[ord(ch)]
        # font units are y-up; SVG is y-down
        gs[g].draw(TransformPen(pen, (scale, 0, 0, -scale, cx, y)))
        cx += hmtx[g][0] * scale + spacing
    d = pen.getCommands()
    return re.sub(r"(\d+\.\d{2})\d+", r"\1", d)  # 2 dp is plenty at this scale


def text_width(s: str, size: float, bold: bool, spacing: float) -> float:
    font = _FONTS.setdefault(bold, _font(bold))
    cmap, hmtx = font.getBestCmap(), font["hmtx"]
    return sum(hmtx[cmap[ord(c)]][0] * size / font["head"].unitsPerEm + spacing for c in s)


TEXT_RE = re.compile(r"<text ([^>]*)>(.*?)</text>")
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def outline_text(svg: str) -> str:
    def repl(m: re.Match) -> str:
        a = dict(ATTR_RE.findall(m.group(1)))
        d = text_path(
            unescape(m.group(2)), float(a["x"]), float(a["y"]), float(a["font-size"]),
            a.get("font-weight") in ("600", "700", "bold"), float(a.get("letter-spacing", 0)),
        )
        return f'<path fill="{a["fill"]}" d="{d}"/>'
    return TEXT_RE.sub(repl, svg)


def tidy(svg: str, label: str) -> str:
    svg = re.sub(r">\s+<", "><", svg.strip())
    return svg.replace("<svg ", f'<svg role="img" aria-label="{label}" ', 1) + "\n"


# ── SVG outputs ──────────────────────────────────────────────────────────────
def build_svgs() -> dict[str, str]:
    out: dict[str, str] = {}
    for variant in ("light", "dark"):
        svg = (SRC / f"logo_{variant}.svg").read_text(encoding="utf-8")
        # The master canvas is 1000 wide but the artwork ends at ~751; trim to
        # equal side margins so the lockup aligns properly in the UI.
        svg = svg.replace('width="1000" height="230" viewBox="0 0 1000 230"',
                          'width="792" height="230" viewBox="0 0 792 230"')
        out[f"madzihub-logo-{variant}.svg"] = tidy(outline_text(svg), "MadziHub — Every drop, accounted for.")

    # Compact wordmark (mark + "MadziHub", no tagline) for small placements,
    # where the tagline's 20px text would shrink to an unreadable smear.
    for variant, ink in (("light", NAVY), ("dark", WHITE)):
        size, spacing, gap = 110, -4, 36
        mark_w = 210 * 1.05                       # mark occupies ~x 20..230
        madzi_w = text_width("Madzi", size, True, spacing)
        x0, base = 20 + mark_w + gap, 152         # baseline centres the caps on the drop
        hub_w = text_width("Hub", size, True, spacing)
        width = round(x0 + madzi_w + hub_w + 20)
        out[f"madzihub-wordmark-{variant}.svg"] = tidy(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="230" viewBox="0 0 {width} 230">'
            f'<g transform="translate(20 11) scale(1.05)">{mark(ink)}</g>'
            f'<path fill="{ink}" d="{text_path("Madzi", x0, base, size, True, spacing)}"/>'
            f'<path fill="{TEAL}" d="{text_path("Hub", x0 + madzi_w, base, size, True, spacing)}"/></svg>',
            "MadziHub")

    # Square mark on transparent — the fallback org logo, shown in a white circle.
    out["madzihub-mark.svg"] = tidy(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240">'
        f'<g transform="translate(20 17)">{mark(NAVY)}</g></svg>', "MadziHub")

    # App icon (navy tile) — as delivered.
    out["madzihub-icon.svg"] = tidy((SRC / "icon.svg").read_text(encoding="utf-8"), "MadziHub")

    # Browser-tab favicon that follows the OS/browser colour scheme: the navy
    # ledger line would vanish on a dark tab strip, so it turns white there.
    out["favicon.svg"] = tidy(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<style>.ink{{fill:{NAVY};stroke:{NAVY}}}path.ink{{fill:none}}'
        f'@media (prefers-color-scheme:dark){{.ink{{fill:{WHITE};stroke:{WHITE}}}path.ink{{fill:none}}}}</style>'
        f'<g transform="translate(1 0) scale(0.31)">{mark(NAVY, "ink")}</g></svg>', "MadziHub")
    return out


# ── raster outputs (rendered by Chromium for exact SVG fidelity) ─────────────
def _chromium() -> str:
    cands = [os.environ.get("CHROMIUM"), shutil.which("chromium"), shutil.which("google-chrome"),
             shutil.which("chrome"), "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"]
    for c in cands:
        if c and Path(c).exists():
            return c
    sys.exit("Chromium not found; set CHROMIUM=/path/to/chrome")


def render(svg: str, size: int) -> Image.Image:
    """Render at >=512px then downsample: Chromium enforces a minimum window
    size, and supersampling gives better small-size anti-aliasing anyway."""
    big = max(size, 512)
    return _render(svg, big).resize((size, size), Image.LANCZOS) if big != size else _render(svg, size)


def _render(svg: str, size: int) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "r.html"
        png = Path(tmp) / "r.png"
        body = re.sub(r'\swidth="\d+"|\sheight="\d+"', "", svg, count=2)
        body = body.replace("<svg ", f'<svg style="display:block" width="{size}" height="{size}" ', 1)
        html.write_text(f"<html><body style='margin:0;background:transparent'>{body}</body></html>")
        subprocess.run([_chromium(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=1", "--default-background-color=00000000",
                        f"--window-size={size},{size + 200}", f"--screenshot={png}", html.as_uri()],
                       check=True, capture_output=True)
        # headless Chromium's viewport is shorter than the window (browser UI),
        # hence the taller window; crop back to the square.
        return Image.open(png).convert("RGBA").crop((0, 0, size, size))


def full_bleed_icon() -> str:
    """Square navy background, no rounded corners — iOS and Android apply their own mask."""
    svg = (SRC / "icon.svg").read_text(encoding="utf-8")
    return re.sub(r'<rect [^>]*/>', f'<rect width="512" height="512" fill="{NAVY}"/>', svg, count=1)


def build_rasters() -> dict[str, bytes]:
    tile = (SRC / "icon.svg").read_text(encoding="utf-8")
    bleed = full_bleed_icon()
    out: dict[str, bytes] = {}

    def png(img: Image.Image) -> bytes:
        b = io.BytesIO(); img.save(b, "PNG", optimize=True); return b.getvalue()

    # Tab/bookmark rasters use the navy tile: legible on light AND dark tab
    # strips, which matters for Safari and .ico consumers that ignore SVG.
    for s in (16, 32, 48):
        out[f"favicon-{s}.png"] = png(render(tile, s))
    ico = render(tile, 64)
    b = io.BytesIO(); ico.save(b, "ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)]); out["favicon.ico"] = b.getvalue()

    out["apple-touch-icon.png"] = png(render(bleed, 180).convert("RGB"))
    out["icon-192.png"] = png(render(tile, 192))
    out["icon-512.png"] = png(render(tile, 512))
    out["icon-maskable-512.png"] = png(render(bleed, 512))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in build_svgs().items():
        (OUT / name).write_text(text, encoding="utf-8")
        print(f"  {name:28s} {len(text.encode()):>7,d} B")
    for name, data in build_rasters().items():
        (OUT / name).write_bytes(data)
        print(f"  {name:28s} {len(data):>7,d} B")


if __name__ == "__main__":
    main()
