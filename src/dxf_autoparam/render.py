"""Pictures of the drawing for the AI (and for reports).

  faithful_png   ezdxf's own renderer: exactly what a CAD viewer shows (texts, hatches, blocks)
  labelled_png   the parsed scene with the set-out lines the model may refer to drawn over it
                 and labelled by id — so an answer can say "x12" instead of guessing coordinates
"""

from __future__ import annotations

import io

import ezdxf
import ezdxf.recover
from PIL import Image, ImageDraw, ImageFont


def faithful_png(path: str, region: tuple[float, float, float, float] | None = None, dpi: int = 110) -> bytes:
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, pymupdf
    from ezdxf.math import BoundingBox2d

    try:
        doc, _ = ezdxf.recover.readfile(path)
    except ezdxf.DXFStructureError:
        doc = ezdxf.readfile(path)
    backend = pymupdf.PyMuPdfBackend()
    cfg = config.Configuration(background_policy=config.BackgroundPolicy.WHITE, color_policy=config.ColorPolicy.BLACK)
    Frontend(RenderContext(doc), backend, config=cfg).draw_layout(doc.modelspace(), finalize=True)
    page = layout.Page(420, 297, layout.Units.mm, margins=layout.Margins.all(4))
    window = BoundingBox2d([(region[0], region[1]), (region[2], region[3])]) if region else None
    return backend.get_pixmap_bytes(page, fmt="png", settings=layout.Settings(fit_page=True), dpi=dpi, render_box=window)


def labelled_png(scene: list[dict], labels: dict[str, tuple[str, float]], bbox: tuple[float, float, float, float],
                 width: int = 1800) -> bytes:
    """Draw the scene; labels: datum id → (axis, value in drawing units)."""
    x0, y0, x1, y1 = bbox
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    pad = 70
    scale = (width - 2 * pad) / w
    height = int(h * scale + 2 * pad)
    if height > 2400:
        scale = (2400 - 2 * pad) / h
        height = 2400
        width = int(w * scale + 2 * pad)
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img, "RGBA")

    def P(p):
        return (pad + (p[0] - x0) * scale, height - pad - (p[1] - y0) * scale)

    for prim in scene:
        role = prim["role"]
        col = (20, 20, 20) if role == "structural" else (200, 40, 40) if role == "reference" else (130, 130, 130) if role == "annotation" else (200, 200, 200)
        if prim["k"] == "p" and len(prim["pts"]) >= 2:
            pts = [P(q) for q in prim["pts"]] + ([P(prim["pts"][0])] if prim.get("closed") else [])
            d.line(pts, fill=col, width=2 if role == "structural" else 1)
        elif prim["k"] == "g" and len(prim["pts"]) >= 3:
            d.polygon([P(q) for q in prim["pts"]], fill=(120, 120, 220, 40))
        elif prim["k"] == "t" and prim.get("text"):
            size = max(9, min(28, int((prim.get("h") or 0) * scale))) if prim.get("h") else 11
            try:
                font = ImageFont.load_default(size)
            except TypeError:
                font = ImageFont.load_default()
            d.text(P(prim["at"]), prim["text"][:60], fill=(90, 90, 90), font=font, anchor="ls")
    try:
        lab = ImageFont.load_default(13)
    except TypeError:
        lab = ImageFont.load_default()
    used_x: list[float] = []
    used_y: list[float] = []
    for did, (axis, v) in sorted(labels.items(), key=lambda t: t[1][1]):
        if axis == "x":
            px = pad + (v - x0) * scale
            d.line([(px, pad - 8), (px, height - pad + 8)], fill=(0, 120, 255, 70), width=1)
            row = sum(1 for u in used_x if abs(u - px) < 34) % 3
            d.text((px, pad - 12 - 15 * row), did, fill=(0, 90, 220), font=lab, anchor="ms")
            used_x.append(px)
        else:
            py = height - pad - (v - y0) * scale
            d.line([(pad - 8, py), (width - pad + 8, py)], fill=(0, 160, 80, 70), width=1)
            col = sum(1 for u in used_y if abs(u - py) < 15) % 3
            d.text((pad - 12 - 40 * col, py), did, fill=(0, 130, 60), font=lab, anchor="rm")
            used_y.append(py)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def regions_png(scene: list[dict], regions: list, bbox: tuple[float, float, float, float], width: int = 1800) -> bytes:
    """The region map: every closed area filled in its own pale colour and labelled with its id (R…)."""
    x0, y0, x1, y1 = bbox
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    pad = 40
    scale = (width - 2 * pad) / w
    height = int(h * scale + 2 * pad)
    if height > 2400:
        scale = (2400 - 2 * pad) / h
        height = 2400
        width = int(w * scale + 2 * pad)
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img, "RGBA")

    def P(p):
        return (pad + (p[0] - x0) * scale, height - pad - (p[1] - y0) * scale)

    palette = [(230, 120, 120), (120, 170, 230), (130, 200, 130), (230, 190, 100), (180, 130, 220), (100, 200, 200), (220, 150, 190), (170, 170, 110)]
    for k, r in enumerate(sorted(regions, key=lambda r: -abs(r.area))):  # big first, nested ones drawn over them
        col = palette[k % len(palette)]
        d.polygon([P(p) for p in r.ring], fill=(*col, 70), outline=(*col, 255))
        for hole in r.holes:
            d.polygon([P(p) for p in hole], fill=(255, 255, 255, 255))
    for prim in scene:
        if prim["k"] == "p" and prim["role"] == "structural" and len(prim["pts"]) >= 2:
            pts = [P(q) for q in prim["pts"]] + ([P(prim["pts"][0])] if prim.get("closed") else [])
            d.line(pts, fill=(30, 30, 30), width=1)
    for r in regions:
        size = int(max(10, min(22, ((r.bbox[2] - r.bbox[0]) * scale) / 4, ((r.bbox[3] - r.bbox[1]) * scale) / 1.2)))
        try:
            font = ImageFont.load_default(size)
        except TypeError:
            font = ImageFont.load_default()
        d.text(P(r.inside), r.id, fill=(0, 0, 0), font=font, anchor="mm", stroke_width=2, stroke_fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
