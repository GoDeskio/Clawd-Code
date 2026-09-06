from __future__ import annotations

import base64
import io
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from src.config import get_provider_config

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".pdf"}


def _pillow() -> tuple[Any, Any, Any, Any]:
    try:
        from PIL import Image, ImageColor, ImageDraw, ImageFont
    except ImportError as exc:
        raise ToolExecutionError("Image Studio dependencies are missing; restart Jonathan Ai to auto-install them") from exc
    return Image, ImageColor, ImageDraw, ImageFont


def _output_path(value: Any, context: ToolContext, default_name: str) -> Path:
    text = str(value or default_name)
    path = context.ensure_allowed_path(text)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ToolInputError(f"unsupported image format: {path.suffix or '(missing extension)'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _source_path(value: Any, context: ToolContext) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError("source is required for this action")
    path = context.ensure_allowed_path(value)
    if not path.is_file():
        raise ToolInputError(f"image not found: {path}")
    return path


def _save(image: Any, path: Path, quality: int = 95) -> None:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"} and image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    kwargs: dict[str, Any] = {}
    if suffix in {".jpg", ".jpeg", ".webp"}:
        kwargs["quality"] = max(1, min(100, int(quality)))
    if suffix == ".png":
        kwargs["optimize"] = True
    image.save(path, **kwargs)


def _publish(path: Path, context: ToolContext) -> list[dict[str, Any]]:
    if context.artifact_publisher is None:
        return []
    return [context.artifact_publisher(path, path.name)]


def _load_font(ImageFont: Any, font: str, size: int) -> Any:
    candidates = [font] if font else []
    candidates += ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _image_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/images/generations"):
        return base
    if not base.endswith("/v1"):
        base += "/v1"
    return base + "/images/generations"


def _image_edit_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/images/edits"):
        return base
    if not base.endswith("/v1"):
        base += "/v1"
    return base + "/images/edits"


def _decode_image_response(data: dict[str, Any]) -> bytes:
    first = (data.get("data") or [None])[0]
    if not isinstance(first, dict):
        raise ToolExecutionError("image provider returned no image")
    if first.get("b64_json"):
        return base64.b64decode(first["b64_json"])
    if first.get("url"):
        with urllib.request.urlopen(str(first["url"]), timeout=180) as response:
            return response.read()
    raise ToolExecutionError("image provider returned no image")


class ImageStudioTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ImageStudio",
            description=(
                "Create or AI-generate images; add or remove text; crop, resize, rotate, flip, composite, "
                "and convert PNG/JPEG/WebP/BMP/GIF/TIFF/PDF. Generation defaults to the installed local "
                "Jonathan local diffusion engine. ai_edit creates a prompt-guided local variation from an uploaded source image. "
                "Finished images are downloadable."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["create", "generate", "ai_edit", "add_text", "remove_text", "resize", "crop", "rotate", "flip", "composite", "convert"]},
                    "engine": {"type": "string", "enum": ["local", "fooocus-local", "cloud"]},
                    "source": {"type": "string"},
                    "overlay": {"type": "string"},
                    "output": {"type": "string"},
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string"},
                    "performance": {"type": "string", "enum": ["Speed", "Quality", "Extreme Speed", "Lightning", "Hyper-SD"]},
                    "variation": {"type": "string", "enum": ["Vary (Subtle)", "Vary (Strong)"]},
                    "seed": {"type": "integer", "minimum": 0},
                    "model": {"type": "string"},
                    "endpoint": {"type": "string"},
                    "width": {"type": "integer", "minimum": 1, "maximum": 16384},
                    "height": {"type": "integer", "minimum": 1, "maximum": 16384},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "crop_width": {"type": "integer", "minimum": 1},
                    "crop_height": {"type": "integer", "minimum": 1},
                    "angle": {"type": "number"},
                    "direction": {"type": "string", "enum": ["horizontal", "vertical"]},
                    "text": {"type": "string"},
                    "font": {"type": "string"},
                    "font_size": {"type": "integer", "minimum": 1, "maximum": 2048},
                    "color": {"type": "string"},
                    "background": {"type": "string"},
                    "stroke_color": {"type": "string"},
                    "stroke_width": {"type": "integer", "minimum": 0, "maximum": 100},
                    "align": {"type": "string", "enum": ["left", "center", "right"]},
                    "gradient_to": {"type": "string"},
                    "regions": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "width": {"type": "integer", "minimum": 1}, "height": {"type": "integer", "minimum": 1}}, "required": ["x", "y", "width", "height"]}},
                    "inpaint_radius": {"type": "number", "minimum": 1, "maximum": 100},
                    "quality": {"type": "integer", "minimum": 1, "maximum": 100},
                    "opacity": {"type": "number", "minimum": 0, "maximum": 1}
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=30_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        action = str(tool_input.get("action") or "image operation")
        return maybe_ask_for_gated_tool(
            context,
            "ImageStudio",
            f"Run Image Studio action '{action}' and create a downloadable file",
            "Allow Image Studio for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        Image, ImageColor, ImageDraw, ImageFont = _pillow()
        action = str(tool_input["action"])
        output = _output_path(tool_input.get("output"), context, f"media/image-{action}.png")
        quality = int(tool_input.get("quality") or 95)

        generation: dict[str, Any] = {}
        if action == "generate":
            generation = self._generate(tool_input, output)
        elif action == "ai_edit":
            source = _source_path(tool_input.get("source"), context)
            generation = self._ai_edit(tool_input, source, output)
        elif action == "create":
            width = int(tool_input.get("width") or 1024)
            height = int(tool_input.get("height") or 1024)
            background = str(tool_input.get("background") or "transparent")
            if tool_input.get("gradient_to"):
                top = ImageColor.getrgb(background)
                bottom = ImageColor.getrgb(str(tool_input["gradient_to"]))
                gradient = Image.new("RGB", (1, height))
                pixels = gradient.load()
                for row in range(height):
                    ratio = row / max(1, height - 1)
                    pixels[0, row] = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom))
                image = gradient.resize((width, height))
            else:
                image = Image.new("RGBA", (width, height), background)
            _save(image, output, quality)
        else:
            source = _source_path(tool_input.get("source"), context)
            with Image.open(source) as opened:
                image = opened.convert("RGBA")
            if action == "add_text":
                draw = ImageDraw.Draw(image)
                text = str(tool_input.get("text") or "")
                if not text:
                    raise ToolInputError("text is required for add_text")
                font = _load_font(ImageFont, str(tool_input.get("font") or ""), int(tool_input.get("font_size") or 48))
                x, y = int(tool_input.get("x") or 0), int(tool_input.get("y") or 0)
                align = str(tool_input.get("align") or "left")
                box = draw.textbbox((0, 0), text, font=font, stroke_width=int(tool_input.get("stroke_width") or 0))
                text_width = box[2] - box[0]
                if align == "center":
                    x = (image.width - text_width) // 2 if "x" not in tool_input else x
                elif align == "right":
                    x = image.width - text_width - x
                draw.text((x, y), text, font=font, fill=str(tool_input.get("color") or "white"),
                          stroke_width=int(tool_input.get("stroke_width") or 0),
                          stroke_fill=str(tool_input.get("stroke_color") or "black"))
            elif action == "remove_text":
                image = self._remove_regions(image, tool_input.get("regions") or [], float(tool_input.get("inpaint_radius") or 5))
            elif action == "resize":
                width = int(tool_input.get("width") or image.width)
                height = int(tool_input.get("height") or image.height)
                image = image.resize((width, height), Image.Resampling.LANCZOS)
            elif action == "crop":
                x, y = int(tool_input.get("x") or 0), int(tool_input.get("y") or 0)
                width = int(tool_input.get("crop_width") or tool_input.get("width") or image.width - x)
                height = int(tool_input.get("crop_height") or tool_input.get("height") or image.height - y)
                image = image.crop((x, y, x + width, y + height))
            elif action == "rotate":
                image = image.rotate(float(tool_input.get("angle") or 0), expand=True, resample=Image.Resampling.BICUBIC)
            elif action == "flip":
                transpose = Image.Transpose.FLIP_LEFT_RIGHT if tool_input.get("direction", "horizontal") == "horizontal" else Image.Transpose.FLIP_TOP_BOTTOM
                image = image.transpose(transpose)
            elif action == "composite":
                overlay_path = _source_path(tool_input.get("overlay"), context)
                overlay = Image.open(overlay_path).convert("RGBA")
                opacity = float(tool_input.get("opacity", 1.0))
                if opacity < 1:
                    overlay.putalpha(overlay.getchannel("A").point(lambda p: int(p * opacity)))
                image.alpha_composite(overlay, (int(tool_input.get("x") or 0), int(tool_input.get("y") or 0)))
            elif action != "convert":
                raise ToolInputError(f"unsupported action: {action}")
            _save(image, output, quality)

        artifacts = _publish(output, context)
        with Image.open(output) as result_image:
            result_width = result_image.width
            result_height = result_image.height
            result_format = result_image.format or output.suffix.lstrip(".").upper()
        return ToolResult(name="ImageStudio", output={
            "action": action,
            "path": str(output),
            "width": result_width,
            "height": result_height,
            "format": result_format,
            **generation,
            "artifact": artifacts[0] if artifacts else None,
            "artifacts": artifacts,
        })

    @staticmethod
    def _remove_regions(image: Any, regions: list[dict[str, Any]], radius: float) -> Any:
        if not regions:
            raise ToolInputError("regions is required for remove_text; provide x, y, width, and height for each text area")
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise ToolExecutionError("OpenCV image inpainting is missing; restart Jonathan Ai to auto-install it") from exc
        rgb = np.array(image.convert("RGB"))
        mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
        for region in regions:
            x, y = int(region["x"]), int(region["y"])
            width, height = int(region["width"]), int(region["height"])
            cv2.rectangle(mask, (x, y), (x + width, y + height), 255, -1)
        restored = cv2.inpaint(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), mask, radius, cv2.INPAINT_TELEA)
        Image, _, _, _ = _pillow()
        return Image.fromarray(cv2.cvtColor(restored, cv2.COLOR_BGR2RGB))

    @staticmethod
    def _generate(tool_input: dict[str, Any], output: Path) -> dict[str, Any]:
        config = get_provider_config("openai")
        api_key = str(config.get("api_key") or "").strip()
        base_url = str(tool_input.get("endpoint") or config.get("base_url") or "https://api.openai.com/v1")
        prompt = str(tool_input.get("prompt") or "").strip()
        if not prompt:
            raise ToolInputError("prompt is required for generate")
        engine = str(tool_input.get("engine") or "local").strip().lower()

        def generate_local(cloud_warning: str = "") -> dict[str, Any]:
            from src.install.record import resolve_source_dir
            from src.integrations.fooocus import FooocusManager

            manager = FooocusManager(resolve_source_dir() or Path.cwd())
            try:
                generated = manager.generate(
                    prompt,
                    negative_prompt=str(tool_input.get("negative_prompt") or ""),
                    width=int(tool_input.get("width") or 1024),
                    height=int(tool_input.get("height") or 1024),
                    performance=str(tool_input.get("performance") or "Speed"),
                    seed=int(tool_input["seed"]) if tool_input.get("seed") is not None else None,
                )
            except Exception as exc:
                prefix = f"{cloud_warning}; " if cloud_warning else ""
                raise ToolExecutionError(f"{prefix}Jonathan local image generation failed: {exc}") from exc
            shutil.copy2(generated["outputs"][0]["path"], output)
            result = {"engine": "jonathan-local-diffusion"}
            if cloud_warning:
                result["warning"] = cloud_warning
            if generated.get("client_warning"):
                result["warning"] = str(generated["client_warning"])
            return result

        # Local generation is deterministic routing, not merely the absence of
        # a cloud key. This prevents stale OpenAI credentials from hijacking an
        # otherwise healthy Jonathan local image engine.
        if engine != "cloud":
            return generate_local()
        if not api_key:
            return generate_local("Cloud image generation is not authenticated; used Jonathan's local engine")

        width, height = int(tool_input.get("width") or 1024), int(tool_input.get("height") or 1024)
        payload = {
            "model": str(tool_input.get("model") or "gpt-image-1"),
            "prompt": prompt,
            "size": "1536x1024" if width > height else ("1024x1536" if height > width else "1024x1024"),
        }
        request = urllib.request.Request(
            _image_endpoint(base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = json.loads(response.read().decode("utf-8"))
            raw = _decode_image_response(data)
            Image, _, _, _ = _pillow()
            image = Image.open(io.BytesIO(raw))
            _save(image, output)
            return {"engine": "cloud"}
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return generate_local(f"Cloud image endpoint returned HTTP {exc.code}; used Jonathan's local engine")
            raise ToolExecutionError(f"cloud image generation failed: HTTP {exc.code}") from exc
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"image generation failed: {exc}") from exc

    @staticmethod
    def _ai_edit(tool_input: dict[str, Any], source: Path, output: Path) -> dict[str, Any]:
        config = get_provider_config("openai")
        api_key = str(config.get("api_key") or "").strip()
        base_url = str(tool_input.get("endpoint") or config.get("base_url") or "https://api.openai.com/v1")
        prompt = str(tool_input.get("prompt") or "").strip()
        if not prompt:
            raise ToolInputError("prompt is required for ai_edit")
        engine = str(tool_input.get("engine") or "local").strip().lower()

        def edit_local(cloud_warning: str = "") -> dict[str, Any]:
            from src.install.record import resolve_source_dir
            from src.integrations.fooocus import FooocusManager

            manager = FooocusManager(resolve_source_dir() or Path.cwd())
            try:
                generated = manager.generate(
                    prompt,
                    negative_prompt=str(tool_input.get("negative_prompt") or ""),
                    width=int(tool_input.get("width") or 1024),
                    height=int(tool_input.get("height") or 1024),
                    performance=str(tool_input.get("performance") or "Speed"),
                    seed=int(tool_input["seed"]) if tool_input.get("seed") is not None else None,
                    source_image=source,
                )
            except Exception as exc:
                prefix = f"{cloud_warning}; " if cloud_warning else ""
                raise ToolExecutionError(f"{prefix}Jonathan local image edit failed: {exc}") from exc
            shutil.copy2(generated["outputs"][0]["path"], output)
            result = {"engine": "jonathan-local-diffusion", "source": str(source)}
            warnings = [item for item in (cloud_warning, generated.get("client_warning")) if item]
            if warnings:
                result["warning"] = "; ".join(str(item) for item in warnings)
            return result

        if engine != "cloud":
            return edit_local()
        if not api_key:
            return edit_local("Cloud image editing is not authenticated; used Jonathan's local engine")
        Image, _, _, _ = _pillow()
        prepared = io.BytesIO()
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
            image.save(prepared, format="PNG")
        boundary = f"----JonathanAi{base64.urlsafe_b64encode(source.name.encode()).decode().rstrip('=')}"
        fields = {
            "model": str(tool_input.get("model") or "gpt-image-1"),
            "prompt": prompt,
            "size": "1024x1024",
        }
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"image.png\"\r\n"
            "Content-Type: image/png\r\n\r\n".encode("utf-8")
        )
        chunks.append(prepared.getvalue())
        chunks.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
        request = urllib.request.Request(
            _image_edit_endpoint(base_url),
            data=b"".join(chunks),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                raw = _decode_image_response(json.loads(response.read().decode("utf-8")))
            with Image.open(io.BytesIO(raw)) as edited:
                _save(edited, output)
            return {"engine": "cloud", "source": str(source)}
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return edit_local(f"Cloud image endpoint returned HTTP {exc.code}; used Jonathan's local engine")
            raise ToolExecutionError(f"cloud image editing failed: HTTP {exc.code}") from exc
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"AI image editing failed: {exc}") from exc
