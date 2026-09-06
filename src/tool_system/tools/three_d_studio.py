from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


FALLBACK_FORMATS = {".glb", ".gltf", ".obj", ".stl", ".ply"}
BLENDER_FORMATS = FALLBACK_FORMATS | {".blend", ".fbx", ".usd", ".usda", ".usdc"}
BLENDER_PORTABLE_VERSION = "5.2.0"
BLENDER_PORTABLE_URL = f"https://download.blender.org/release/Blender5.2/blender-{BLENDER_PORTABLE_VERSION}-windows-x64.zip"
BLENDER_SHA256_URL = f"https://download.blender.org/release/Blender5.2/blender-{BLENDER_PORTABLE_VERSION}.sha256"


def discover_blender() -> str | None:
    found = shutil.which("blender")
    if found:
        return found
    candidates: list[Path] = []
    managed = Path.home() / ".clawd" / "tools" / "blender"
    if managed.is_dir():
        candidates.extend(managed.glob("**/blender.exe"))
    if os.name == "nt":
        for root in (os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if not root:
                continue
            candidates.extend(Path(root).glob("Blender Foundation/Blender */blender.exe"))
            candidates.extend(Path(root).glob("Programs/Blender Foundation/Blender */blender.exe"))
    return str(sorted(candidates)[-1]) if candidates else None


def media_capabilities() -> dict[str, Any]:
    blender = discover_blender()
    return {
        "image": {
            "pillow": importlib.util.find_spec("PIL") is not None,
            "opencv": importlib.util.find_spec("cv2") is not None,
            "formats": ["png", "jpeg", "webp", "bmp", "gif", "tiff", "pdf"],
            "operations": ["generate", "create", "add_text", "remove_text", "resize", "crop", "rotate", "flip", "composite", "convert"],
        },
        "three_d": {
            "trimesh": importlib.util.find_spec("trimesh") is not None,
            "blender": bool(blender),
            "blender_path": blender,
            "formats": sorted(ext.lstrip(".") for ext in BLENDER_FORMATS),
            "fallback_formats": sorted(ext.lstrip(".") for ext in FALLBACK_FORMATS),
            "mlb_alias": "glb",
            "textures": bool(blender),
            "high_definition_rendering": bool(blender),
        },
    }


def _normalise_output(value: Any, context: ToolContext) -> tuple[Path, str | None]:
    text = str(value or "media/model.glb")
    note = None
    if text.lower().endswith(".mlb"):
        text = text[:-4] + ".glb"
        note = "Corrected .mlb to the standard 3D binary format .glb"
    path = context.ensure_allowed_path(text)
    if path.suffix.lower() not in BLENDER_FORMATS:
        raise ToolInputError(f"unsupported 3D output format: {path.suffix or '(missing extension)'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path, note


def _rgba(value: Any) -> list[int]:
    if isinstance(value, list) and len(value) in {3, 4}:
        values = [float(item) for item in value]
        if max(values) <= 1:
            values = [item * 255 for item in values]
        if len(values) == 3:
            values.append(255)
        return [max(0, min(255, round(item))) for item in values]
    text = str(value or "#b9c7ff").strip().lstrip("#")
    if len(text) in {6, 8}:
        try:
            values = [int(text[index:index + 2], 16) for index in range(0, len(text), 2)]
            return values + ([255] if len(values) == 3 else [])
        except ValueError:
            pass
    return [185, 199, 255, 255]


def _vector(value: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if isinstance(value, list) and len(value) == 3:
        return tuple(float(item) for item in value)  # type: ignore[return-value]
    return default


def _publish(paths: list[Path], context: ToolContext) -> list[dict[str, Any]]:
    if context.artifact_publisher is None:
        return []
    return [context.artifact_publisher(path, path.name) for path in paths if path.is_file()]


BLENDER_DRIVER = r'''
import bpy, json, math, os, sys

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
with open(argv[0], "r", encoding="utf-8") as handle:
    spec = json.load(handle)

def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    elif ext in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        (bpy.ops.wm.obj_import if hasattr(bpy.ops.wm, "obj_import") else bpy.ops.import_scene.obj)(filepath=path)
    elif ext == ".stl":
        (bpy.ops.wm.stl_import if hasattr(bpy.ops.wm, "stl_import") else bpy.ops.import_mesh.stl)(filepath=path)
    elif ext == ".ply":
        (bpy.ops.wm.ply_import if hasattr(bpy.ops.wm, "ply_import") else bpy.ops.import_mesh.ply)(filepath=path)
    else:
        raise RuntimeError("Unsupported Blender import: " + ext)

def material_for(item, index):
    material = bpy.data.materials.new("JonathanMaterial%03d" % index)
    material.use_nodes = True
    node = material.node_tree.nodes.get("Principled BSDF")
    color = item.get("color", [0.72, 0.78, 1.0, 1.0])
    if max(color) > 1:
        color = [float(v) / 255.0 for v in color]
    if len(color) == 3:
        color.append(1.0)
    node.inputs["Base Color"].default_value = color
    node.inputs["Metallic"].default_value = float(item.get("metallic", 0.0))
    node.inputs["Roughness"].default_value = float(item.get("roughness", 0.45))
    texture = item.get("texture")
    if texture:
        image = bpy.data.images.load(texture, check_existing=True)
        tex = material.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        material.node_tree.links.new(tex.outputs["Color"], node.inputs["Base Color"])
        material.node_tree.links.new(tex.outputs["Alpha"], node.inputs["Alpha"])
    return material

if spec.get("source"):
    import_model(spec["source"])
else:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

for index, item in enumerate(spec.get("objects", [])):
    kind = item.get("type", "cube").lower()
    segments = max(8, int(item.get("segments", 64)))
    if kind in {"cube", "box"}:
        bpy.ops.mesh.primitive_cube_add(size=float(item.get("size", 2.0)))
    elif kind in {"sphere", "uv_sphere", "icosphere"}:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=max(8, segments // 2), radius=float(item.get("radius", 1.0)))
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=segments, radius=float(item.get("radius", 1.0)), depth=float(item.get("height", 2.0)))
    elif kind == "cone":
        bpy.ops.mesh.primitive_cone_add(vertices=segments, radius1=float(item.get("radius", 1.0)), radius2=float(item.get("radius2", 0.0)), depth=float(item.get("height", 2.0)))
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(major_segments=segments, minor_segments=max(6, segments // 4), major_radius=float(item.get("radius", 1.0)), minor_radius=float(item.get("minor_radius", 0.25)))
    elif kind == "text":
        bpy.ops.object.text_add()
        bpy.context.object.data.body = str(item.get("text", "Jonathan Ai"))
        bpy.context.object.data.extrude = float(item.get("extrude", 0.08))
        bpy.context.object.data.bevel_depth = float(item.get("bevel", 0.02))
    else:
        raise RuntimeError("Unsupported primitive: " + kind)
    obj = bpy.context.object
    obj.name = str(item.get("name", kind + str(index)))
    obj.location = item.get("translate", item.get("location", [0, 0, 0]))
    obj.scale = item.get("scale", [1, 1, 1])
    obj.rotation_euler = [math.radians(float(v)) for v in item.get("rotation", [0, 0, 0])]
    if hasattr(obj.data, "materials"):
        obj.data.materials.append(material_for(item, index))
    if item.get("smooth", True) and obj.type == "MESH":
        for polygon in obj.data.polygons:
            polygon.use_smooth = True

render = spec.get("render") or {}
if render:
    bpy.ops.object.camera_add(location=render.get("camera", [6, -6, 4]))
    camera = bpy.context.object
    bpy.context.scene.camera = camera
    direction = mathutils.Vector(render.get("target", [0, 0, 0])) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.light_add(type="AREA", location=render.get("light", [4, -3, 6]))
    bpy.context.object.data.energy = float(render.get("energy", 1200))
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 5
    scene = bpy.context.scene
    if render.get("engine", "eevee").lower() == "cycles":
        scene.render.engine = "CYCLES"
    else:
        engine_ids = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
        scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engine_ids else "BLENDER_EEVEE"
    scene.render.resolution_x = int(render.get("width", 2048))
    scene.render.resolution_y = int(render.get("height", 2048))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = render["output"]
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = int(render.get("samples", 128))
    bpy.ops.render.render(write_still=True)

output = spec["output"]
ext = os.path.splitext(output)[1].lower()
if ext == ".blend":
    bpy.ops.wm.save_as_mainfile(filepath=output)
elif ext in {".glb", ".gltf"}:
    bpy.ops.export_scene.gltf(filepath=output, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE", export_apply=True)
elif ext == ".fbx":
    bpy.ops.export_scene.fbx(filepath=output, use_selection=False)
elif ext == ".obj":
    (bpy.ops.wm.obj_export if hasattr(bpy.ops.wm, "obj_export") else bpy.ops.export_scene.obj)(filepath=output)
elif ext == ".stl":
    (bpy.ops.wm.stl_export if hasattr(bpy.ops.wm, "stl_export") else bpy.ops.export_mesh.stl)(filepath=output)
elif ext == ".ply":
    (bpy.ops.wm.ply_export if hasattr(bpy.ops.wm, "ply_export") else bpy.ops.export_mesh.ply)(filepath=output)
elif ext in {".usd", ".usda", ".usdc"}:
    bpy.ops.wm.usd_export(filepath=output)
else:
    raise RuntimeError("Unsupported Blender export: " + ext)
'''


class ThreeDStudioTool:
    def spec(self) -> ToolSpec:
        object_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": ["cube", "box", "sphere", "uv_sphere", "icosphere", "cylinder", "cone", "torus", "text"]},
                "name": {"type": "string"}, "text": {"type": "string"},
                "size": {"type": "number", "minimum": 0.0001}, "radius": {"type": "number", "minimum": 0.0001},
                "radius2": {"type": "number", "minimum": 0}, "minor_radius": {"type": "number", "minimum": 0.0001},
                "height": {"type": "number", "minimum": 0.0001}, "segments": {"type": "integer", "minimum": 8, "maximum": 512},
                "translate": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "scale": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "rotation": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 4},
                "texture": {"type": "string"}, "metallic": {"type": "number", "minimum": 0, "maximum": 1},
                "roughness": {"type": "number", "minimum": 0, "maximum": 1}, "smooth": {"type": "boolean"},
                "extrude": {"type": "number", "minimum": 0}, "bevel": {"type": "number", "minimum": 0}
            },
            "required": ["type"]
        }
        return ToolSpec(
            name="ThreeDStudio",
            description=(
                "Create, edit, convert, render, and export colored or textured 3D assets. Supports GLB/GLTF/OBJ/STL/PLY "
                "locally and uses Blender for BLEND/FBX/USD, textures, high-definition rendering, and custom scripts. "
                "Accepts .mlb as an alias for .glb. Use install_blender when Blender is unavailable."
            ),
            input_schema={
                "type": "object", "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["capabilities", "create", "convert", "render", "blender_script", "install_blender"]},
                    "source": {"type": "string"}, "output": {"type": "string"}, "script": {"type": "string"},
                    "objects": {"type": "array", "items": object_schema},
                    "render_output": {"type": "string"}, "render_width": {"type": "integer", "minimum": 64, "maximum": 16384},
                    "render_height": {"type": "integer", "minimum": 64, "maximum": 16384},
                    "samples": {"type": "integer", "minimum": 1, "maximum": 8192},
                    "engine": {"type": "string", "enum": ["eevee", "cycles"]},
                    "camera": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "target": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "light": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "energy": {"type": "number", "minimum": 0}, "timeout": {"type": "integer", "minimum": 1, "maximum": 3600}
                },
                "required": ["action"]
            },
            is_destructive=True, max_result_size_chars=50_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") == "capabilities":
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(
            context, "ThreeDStudio", f"Run 3D Studio action '{tool_input.get('action')}'",
            "Allow 3D Studio for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "capabilities":
            return ToolResult(name="ThreeDStudio", output=media_capabilities())
        if action == "install_blender":
            return self._install_blender(tool_input)
        output, note = _normalise_output(tool_input.get("output"), context)
        source: Path | None = None
        if tool_input.get("source"):
            source = context.ensure_allowed_path(str(tool_input["source"]))
            if not source.is_file():
                raise ToolInputError(f"3D source file not found: {source}")
        render_path: Path | None = None
        if action == "render":
            render_path = context.ensure_allowed_path(str(tool_input.get("render_output") or "media/render.png"))
            if render_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
                raise ToolInputError("render_output must be a standard image file")
            render_path.parent.mkdir(parents=True, exist_ok=True)

        objects = list(tool_input.get("objects") or [])
        requires_blender = (
            action in {"render", "convert", "blender_script"}
            or output.suffix.lower() not in FALLBACK_FORMATS
            or bool(source)
            or any(item.get("texture") or item.get("type") == "text" for item in objects)
        )
        if requires_blender:
            self._run_blender(action, source, output, render_path, objects, tool_input, context)
        else:
            self._run_trimesh(output, objects)

        paths = [output] + ([render_path] if render_path and render_path.exists() else [])
        artifacts = _publish([path for path in paths if path is not None], context)
        return ToolResult(name="ThreeDStudio", output={
            "action": action, "path": str(output), "render_path": str(render_path) if render_path else None,
            "format": output.suffix.lstrip(".").lower(), "note": note,
            "engine": "blender" if requires_blender else "trimesh", "artifact": artifacts[0] if artifacts else None,
            "artifacts": artifacts,
        })

    @staticmethod
    def _run_trimesh(output: Path, objects: list[dict[str, Any]]) -> None:
        try:
            import trimesh
        except ImportError as exc:
            raise ToolExecutionError("3D dependencies are missing; restart Jonathan Ai to auto-install them") from exc
        if not objects:
            objects = [{"type": "cube", "size": 2, "color": [185, 199, 255, 255]}]
        scene = trimesh.Scene()
        for index, item in enumerate(objects):
            kind = str(item.get("type") or "cube").lower()
            segments = int(item.get("segments") or 64)
            if kind in {"cube", "box"}:
                size = float(item.get("size") or 2)
                mesh = trimesh.creation.box(extents=[size, size, size])
            elif kind in {"sphere", "uv_sphere"}:
                mesh = trimesh.creation.uv_sphere(radius=float(item.get("radius") or 1), count=[segments, max(8, segments // 2)])
            elif kind == "icosphere":
                subdivisions = max(1, min(5, round(math.log2(max(8, segments) / 8))))
                mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=float(item.get("radius") or 1))
            elif kind == "cylinder":
                mesh = trimesh.creation.cylinder(radius=float(item.get("radius") or 1), height=float(item.get("height") or 2), sections=segments)
            elif kind == "cone":
                mesh = trimesh.creation.cone(radius=float(item.get("radius") or 1), height=float(item.get("height") or 2), sections=segments)
            elif kind == "torus":
                mesh = trimesh.creation.torus(major_radius=float(item.get("radius") or 1), minor_radius=float(item.get("minor_radius") or .25), major_sections=segments, minor_sections=max(8, segments // 4))
            else:
                raise ToolInputError(f"{kind} requires Blender or is not a supported primitive")
            # Vertex colors export to GLB without pulling in trimesh's optional
            # SciPy face-to-vertex conversion dependency.
            mesh.visual.vertex_colors = _rgba(item.get("color"))
            transform = trimesh.transformations.compose_matrix(
                scale=_vector(item.get("scale"), (1, 1, 1)),
                angles=tuple(math.radians(v) for v in _vector(item.get("rotation"), (0, 0, 0))),
                translate=_vector(item.get("translate"), (0, 0, 0)),
            )
            scene.add_geometry(mesh, node_name=str(item.get("name") or f"{kind}-{index}"), transform=transform)
        try:
            scene.export(str(output))
        except Exception as exc:
            raise ToolExecutionError(f"3D export failed: {exc}") from exc
        if not output.exists():
            raise ToolExecutionError(f"3D exporter did not create {output}")

    @staticmethod
    def _run_blender(action: str, source: Path | None, output: Path, render_path: Path | None,
                     objects: list[dict[str, Any]], tool_input: dict[str, Any], context: ToolContext) -> None:
        blender = discover_blender()
        if not blender:
            raise ToolExecutionError(
                "Blender is required for this 3D operation. Run ThreeDStudio with action=install_blender, approve the install, then retry."
            )
        if action == "blender_script":
            script = str(tool_input.get("script") or "").strip()
            if not script:
                raise ToolInputError("script is required for blender_script")
            with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
                handle.write(script)
                script_path = Path(handle.name)
            command = [blender, "--background", "--python", str(script_path), "--", str(output)]
        else:
            normalised_objects: list[dict[str, Any]] = []
            for item in objects:
                row = dict(item)
                row["color"] = _rgba(row.get("color"))
                if row.get("texture"):
                    row["texture"] = str(context.ensure_allowed_path(str(row["texture"])))
                normalised_objects.append(row)
            spec = {"source": str(source) if source else None, "output": str(output), "objects": normalised_objects}
            if render_path:
                spec["render"] = {
                    "output": str(render_path), "width": int(tool_input.get("render_width") or 2048),
                    "height": int(tool_input.get("render_height") or 2048), "samples": int(tool_input.get("samples") or 128),
                    "engine": str(tool_input.get("engine") or "eevee"), "camera": tool_input.get("camera") or [6, -6, 4],
                    "target": tool_input.get("target") or [0, 0, 0], "light": tool_input.get("light") or [4, -3, 6],
                    "energy": float(tool_input.get("energy") or 1200),
                }
            with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as spec_handle:
                json.dump(spec, spec_handle, ensure_ascii=False)
                spec_path = Path(spec_handle.name)
            with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as script_handle:
                script_handle.write("import mathutils\n" + BLENDER_DRIVER)
                script_path = Path(script_handle.name)
            command = [blender, "--background", "--python", str(script_path), "--", str(spec_path)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                       timeout=int(tool_input.get("timeout") or 900), cwd=str(context.cwd))
        finally:
            script_path.unlink(missing_ok=True)
            if action != "blender_script":
                spec_path.unlink(missing_ok=True)
        combined_output = (completed.stderr + "\n" + completed.stdout).strip()
        if completed.returncode != 0 or "Traceback (most recent call last)" in combined_output:
            detail = (combined_output or "unknown Blender error")[-5000:]
            raise ToolExecutionError(f"Blender failed ({completed.returncode}): {detail}")
        if not output.exists():
            detail = (completed.stderr + "\n" + completed.stdout).strip()[-5000:]
            raise ToolExecutionError(f"Blender completed without creating the requested model: {detail}")

    @staticmethod
    def _install_blender(tool_input: dict[str, Any]) -> ToolResult:
        if discover_blender():
            return ToolResult(name="ThreeDStudio", output={"installed": True, "blender_path": discover_blender(), "message": "Blender is already installed"})
        winget = shutil.which("winget")
        if winget:
            command = [winget, "install", "--id", "BlenderFoundation.Blender", "--exact", "--silent",
                       "--accept-package-agreements", "--accept-source-agreements"]
            try:
                completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                           timeout=int(tool_input.get("timeout") or 1800))
            except subprocess.TimeoutExpired:
                return ToolResult(name="ThreeDStudio", output={"installed": False, "error": "Blender installation timed out; it may still be completing in the background"}, is_error=True)
            blender = discover_blender()
            return ToolResult(name="ThreeDStudio", output={
                "installed": bool(blender), "blender_path": blender, "exit_code": completed.returncode,
                "stdout": completed.stdout[-3000:], "stderr": completed.stderr[-3000:],
                "message": "Blender installed" if blender else "Blender installation failed",
            }, is_error=completed.returncode != 0 or not blender)

        if os.name != "nt":
            return ToolResult(name="ThreeDStudio", output={"installed": False, "error": "No supported package manager was found; install Blender and restart Jonathan Ai"}, is_error=True)
        # Windows App Installer/winget is absent on some machines. In that case
        # install Blender's official portable build into Jonathan's managed tools.
        target_root = Path.home() / ".clawd" / "tools" / "blender"
        target_root.mkdir(parents=True, exist_ok=True)
        archive = target_root / f"blender-{BLENDER_PORTABLE_VERSION}-windows-x64.zip"
        url = os.environ.get("JONATHAN_BLENDER_URL") or BLENDER_PORTABLE_URL
        sha_url = os.environ.get("JONATHAN_BLENDER_SHA256_URL") or BLENDER_SHA256_URL
        try:
            if not archive.exists():
                urllib.request.urlretrieve(url, archive)
            hasher = hashlib.sha256()
            with archive.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            digest = hasher.hexdigest().lower()
            expected = ""
            with urllib.request.urlopen(sha_url, timeout=60) as response:
                checksum_text = response.read().decode("utf-8", errors="replace")
            for line in checksum_text.splitlines():
                if archive.name in line:
                    expected = line.split()[0].lower()
                    break
            if not expected or digest != expected:
                archive.unlink(missing_ok=True)
                raise ToolExecutionError("Blender portable checksum verification failed")
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target_root)
            archive.unlink(missing_ok=True)
        except Exception as exc:
            return ToolResult(name="ThreeDStudio", output={"installed": False, "error": f"portable Blender installation failed: {exc}", "url": url}, is_error=True)
        blender = discover_blender()
        return ToolResult(name="ThreeDStudio", output={"installed": bool(blender), "blender_path": blender,
            "version": BLENDER_PORTABLE_VERSION, "source": url, "verified_sha256": digest,
            "message": "Official portable Blender installed in Jonathan Ai's managed tools"}, is_error=not bool(blender))
