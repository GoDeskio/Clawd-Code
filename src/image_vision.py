"""Fast local image inspection that complements a connected vision model."""

from __future__ import annotations

import math
import threading
from collections import Counter
from pathlib import Path
from typing import Any

_OCR_LOCK = threading.Lock()
_OCR_ENGINE: Any | None = None

_COLOR_NAMES = {
    "black": (0, 0, 0), "white": (255, 255, 255), "gray": (128, 128, 128),
    "red": (220, 40, 40), "orange": (242, 133, 32), "yellow": (240, 220, 40),
    "green": (45, 155, 70), "cyan": (35, 190, 190), "blue": (45, 90, 210),
    "purple": (135, 70, 185), "pink": (225, 105, 165), "brown": (130, 85, 50),
    "beige": (220, 205, 170), "navy": (20, 40, 90),
}


def _nearest_color(rgb: tuple[int, int, int]) -> str:
    return min(
        _COLOR_NAMES,
        key=lambda name: sum((rgb[index] - _COLOR_NAMES[name][index]) ** 2 for index in range(3)),
    )


def _dominant_colors(image: Any, count: int = 6) -> list[dict[str, Any]]:
    sample = image.convert("RGB")
    sample.thumbnail((256, 256))
    quantized = sample.quantize(colors=count)
    palette = quantized.getpalette() or []
    histogram = quantized.getcolors(maxcolors=256 * 256) or []
    total = max(1, sum(amount for amount, _ in histogram))
    rows: list[dict[str, Any]] = []
    for amount, index in sorted(histogram, reverse=True)[:count]:
        rgb = tuple(int(value) for value in palette[index * 3:index * 3 + 3])
        if len(rgb) != 3:
            continue
        rows.append({
            "name": _nearest_color(rgb),
            "rgb": list(rgb),
            "hex": "#%02x%02x%02x" % rgb,
            "percent": round(amount * 100 / total, 1),
        })
    return rows


def _ocr(np_rgb: Any) -> tuple[list[dict[str, Any]], str]:
    global _OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return [], "RapidOCR is not installed"
    with _OCR_LOCK:
        if _OCR_ENGINE is None:
            _OCR_ENGINE = RapidOCR()
        engine = _OCR_ENGINE
    try:
        result, _elapsed = engine(np_rgb)
    except Exception as exc:
        return [], f"OCR failed: {exc}"
    rows: list[dict[str, Any]] = []
    for item in result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        text = str(item[1] or "").strip()
        if not text:
            continue
        rows.append({"text": text, "confidence": round(float(item[2]), 3), "box": item[0]})
    return rows[:100], "ready"


def inspect_image(path: str | Path, *, run_ocr: bool = False) -> dict[str, Any]:
    """Inspect pixels locally for color, shape, people/face, QR, and optional text."""
    from PIL import Image, ImageStat

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"image not found: {source}")
    with Image.open(source) as opened:
        opened.seek(0)
        rgb = opened.convert("RGB")
        info = {
            "path": str(source), "format": opened.format or source.suffix.lstrip(".").upper(),
            "width": opened.width, "height": opened.height, "mode": opened.mode,
            "frames": int(getattr(opened, "n_frames", 1) or 1),
        }
        colors = _dominant_colors(rgb)
        stat = ImageStat.Stat(rgb.convert("L"))
        brightness = round(float(stat.mean[0]), 1)
        contrast = round(float(stat.stddev[0]), 1)

    try:
        import cv2
        import numpy as np
    except ImportError:
        return {**info, "dominant_colors": colors, "brightness": brightness, "contrast": contrast,
                "objects": [], "shapes": {}, "text": [], "warning": "OpenCV is not installed"}

    np_rgb = np.asarray(rgb)
    bgr = cv2.cvtColor(np_rgb, cv2.COLOR_RGB2BGR)
    scale = min(1.0, 960.0 / max(bgr.shape[:2]))
    working = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else bgr
    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 60, 150)
    contours, _hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(working.shape[0] * working.shape[1])
    shape_counts: Counter[str] = Counter()
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < max(80.0, image_area * 0.0008) or area > image_area * 0.92:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        vertices = len(cv2.approxPolyDP(contour, 0.035 * perimeter, True))
        circularity = 4 * math.pi * area / (perimeter * perimeter)
        if vertices == 3:
            label = "triangle"
        elif vertices == 4:
            x, y, width, height = cv2.boundingRect(contour)
            label = "square" if 0.88 <= width / max(1, height) <= 1.12 else "rectangle"
        elif circularity >= 0.72:
            label = "circle"
        elif vertices <= 8:
            label = "polygon"
        else:
            continue
        shape_counts[label] += 1

    objects: list[dict[str, Any]] = []
    try:
        cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
        faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28))
        if len(faces):
            objects.append({"label": "face", "count": int(len(faces)), "detector": "opencv-haar"})
    except Exception:
        pass
    try:
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        people, _weights = hog.detectMultiScale(working, winStride=(8, 8), padding=(8, 8), scale=1.08)
        if len(people):
            objects.append({"label": "person", "count": int(len(people)), "detector": "opencv-hog"})
    except Exception:
        pass
    qr_text = ""
    try:
        qr_text, _points, _straight = cv2.QRCodeDetector().detectAndDecode(working)
        if qr_text:
            objects.append({"label": "qr-code", "count": 1, "value": qr_text, "detector": "opencv-qr"})
    except Exception:
        pass

    text, ocr_status = _ocr(np_rgb) if run_ocr else ([], "not requested")
    sharpness = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1)
    return {
        **info,
        "orientation": "landscape" if info["width"] > info["height"] else "portrait" if info["height"] > info["width"] else "square",
        "dominant_colors": colors,
        "brightness": brightness,
        "contrast": contrast,
        "sharpness": sharpness,
        "objects": objects,
        "shapes": dict(shape_counts.most_common()),
        "text": text,
        "ocr_status": ocr_status,
        "semantic_object_recognition": "The connected vision model receives the original pixels for broader semantic identification.",
    }


def compact_image_brief(result: dict[str, Any]) -> str:
    colors = ", ".join(f"{row['name']} {row['percent']}%" for row in result.get("dominant_colors") or [])
    objects = ", ".join(f"{row['label']}×{row.get('count', 1)}" for row in result.get("objects") or []) or "none from local detectors"
    shapes = ", ".join(f"{name}×{count}" for name, count in (result.get("shapes") or {}).items()) or "none"
    text = " | ".join(row.get("text", "") for row in result.get("text") or [])
    return (
        f"{result.get('width')}×{result.get('height')} {result.get('format')} {result.get('orientation')}; "
        f"colors: {colors or 'unknown'}; local objects: {objects}; shapes: {shapes}"
        + (f"; OCR: {text}" if text else "")
    )
