"""Image optimisation of uploads: photos larger than the limit are scaled down and stored as WebP (smaller
pages, faster sites). GIF (animation), SVG and anything that would get bigger are kept as they are.
Turned off with app.optimize_images = false."""
import io
from pathlib import PurePosixPath

from buildweb import config

MAX_SIDE = 2000
QUALITY = 82
CONVERT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def enabled():
    return config.load()["app"].get("optimize_images", True)


def optimize_upload(name, fileobj):
    """(new name, bytes) of an optimised copy, or None to keep the original."""
    ext = PurePosixPath(name).suffix.lower()
    if ext not in CONVERT or not enabled():
        return None
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    raw = fileobj.read()
    fileobj.seek(0)
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)  # phone photos come rotated by EXIF
        if getattr(img, "is_animated", False):
            return None
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=QUALITY, method=6)
    except Exception:
        return None  # not an image Pillow understands: keep the upload untouched
    data = out.getvalue()
    if len(data) >= len(raw) and ext == ".webp":
        return None
    if len(data) >= len(raw) * 0.95 and max(Image.open(io.BytesIO(raw)).size) <= MAX_SIDE:
        return None
    return str(PurePosixPath(name).with_suffix(".webp")), data


def shrink_in_place(path):
    """Existing files: scale down oversized JPG/PNG keeping name and format (links stay valid).
    Returns bytes saved."""
    from PIL import Image, ImageOps

    before = path.stat().st_size
    try:
        img = ImageOps.exif_transpose(Image.open(path))
        if max(img.size) <= MAX_SIDE or getattr(img, "is_animated", False):
            return 0
        fmt = (Image.open(path).format or "").upper()
        if fmt not in ("JPEG", "PNG", "WEBP"):
            return 0
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        if fmt == "JPEG":
            img.convert("RGB").save(buf, "JPEG", quality=85, optimize=True, progressive=True)
        else:
            img.save(buf, fmt, optimize=True) if fmt == "PNG" else img.save(buf, fmt, quality=QUALITY)
    except Exception:
        return 0
    if buf.tell() >= before:
        return 0
    path.write_bytes(buf.getvalue())
    return before - buf.tell()
