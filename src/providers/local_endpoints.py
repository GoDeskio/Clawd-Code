"""Discover OpenAI-compatible local LLM servers on loopback/LAN only.

Never contacts Hugging Face or any public WAN host. Custom URLs are rejected
unless the hostname resolves only to loopback or private LAN addresses.
"""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ProbeFn = Callable[[str, float, dict[str, str] | None], tuple[int, Any]]

LOCAL_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "ollama",
        "label": "Ollama",
        "urls": ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434"),
        "default_url": "http://127.0.0.1:11434/v1",
    },
    {
        "id": "lmstudio",
        "label": "LM Studio",
        "urls": ("http://127.0.0.1:1234/v1",),
        "default_url": "http://127.0.0.1:1234/v1",
    },
    {
        "id": "vllm",
        "label": "vLLM",
        "urls": ("http://127.0.0.1:8000/v1",),
        "default_url": "http://127.0.0.1:8000/v1",
    },
    {
        "id": "llamacpp",
        "label": "llama.cpp server",
        "urls": ("http://127.0.0.1:8080/v1",),
        "default_url": "http://127.0.0.1:8080/v1",
    },
    {
        "id": "tgi",
        "label": "Hugging Face TGI",
        "urls": ("http://127.0.0.1:3000/v1", "http://127.0.0.1:8080"),
        "default_url": "http://127.0.0.1:3000/v1",
    },
    {
        "id": "localai",
        "label": "LocalAI",
        "urls": ("http://127.0.0.1:8080/v1",),
        "default_url": "http://127.0.0.1:8080/v1",
    },
    {
        "id": "koboldcpp",
        "label": "KoboldCpp",
        "urls": ("http://127.0.0.1:5001/v1",),
        "default_url": "http://127.0.0.1:5001/v1",
    },
    {
        "id": "jan",
        "label": "Jan",
        "urls": ("http://127.0.0.1:1337/v1",),
        "default_url": "http://127.0.0.1:1337/v1",
    },
)


class RemoteEndpointError(ValueError):
    """Raised when a URL is not loopback/LAN."""


def _host_is_loopback_or_lan(host: str) -> bool:
    raw = (host or "").strip().strip("[]")
    if not raw:
        return False
    lowered = raw.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(raw)
        return bool(ip.is_loopback or ip.is_private or ip.is_link_local)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(raw, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            return False
    return True


def assert_local_or_lan_url(url: str) -> str:
    """Accept only http(s) URLs whose host is loopback or RFC1918/LAN."""
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise RemoteEndpointError("local endpoints must be http or https")
    if not parsed.hostname:
        raise RemoteEndpointError("local endpoint is missing a host")
    if not _host_is_loopback_or_lan(parsed.hostname):
        raise RemoteEndpointError(
            f"refusing WAN host {parsed.hostname!r}; local LLMs stay on loopback/LAN"
        )
    return raw.rstrip("/")


def normalize_openai_base(url: str) -> str:
    raw = assert_local_or_lan_url(url)
    if raw.endswith("/v1"):
        return raw
    return f"{raw}/v1"


def http_json(
    url: str,
    *,
    timeout: float = 0.8,
    headers: dict[str, str] | None = None,
    allow_wan: bool = False,
) -> tuple[int, Any]:
    if not allow_wan:
        assert_local_or_lan_url(url)
    req = Request(url, headers={"Accept": "application/json", **(headers or {})}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        status = int(exc.code)
    except URLError as exc:
        raise ConnectionError(str(exc.reason or exc)) from exc
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status, raw.decode("utf-8", errors="replace")


def _auth_headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key or key == "local":
        return {}
    return {"Authorization": f"Bearer {key}"}


def _model_ids(payload: Any) -> list[str]:
    names: list[str] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    names.append(str(item["id"]))
        models = payload.get("models")
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("model") or item.get("id")
                    if name:
                        names.append(str(name))
                elif isinstance(item, str):
                    names.append(item)
        model_id = payload.get("model_id") or payload.get("model")
        if isinstance(model_id, str) and model_id:
            names.append(model_id)
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def list_local_models(
    base_url: str,
    api_key: str | None = None,
    *,
    timeout: float = 1.5,
    probe: ProbeFn | None = None,
) -> list[str]:
    """List models from an OpenAI-compatible or Ollama local server."""
    root = assert_local_or_lan_url(base_url)
    do_probe = probe or (lambda url, t, headers: http_json(url, timeout=t, headers=headers))
    headers = _auth_headers(api_key)
    candidates = []
    if root.endswith("/v1"):
        candidates.append(f"{root}/models")
        candidates.append(f"{root[:-3]}/api/tags")
        candidates.append(f"{root[:-3]}/info")
    else:
        candidates.append(f"{root}/v1/models")
        candidates.append(f"{root}/api/tags")
        candidates.append(f"{root}/info")
        candidates.append(f"{root}/models")
    last_error = ""
    for url in candidates:
        try:
            status, payload = do_probe(url, timeout, headers)
        except Exception as exc:  # noqa: BLE001 — probe next candidate
            last_error = str(exc)
            continue
        if status >= 400:
            last_error = f"{url} -> {status}"
            continue
        names = _model_ids(payload)
        if names:
            return names
    if last_error:
        raise ConnectionError(last_error)
    return []


def _probe_preset(
    preset: dict[str, Any],
    probe: ProbeFn,
    timeout: float,
) -> dict[str, Any] | None:
    last_error = ""
    for url in preset["urls"]:
        try:
            models = list_local_models(url, probe=probe, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
        return {
            "id": preset["id"],
            "label": preset["label"],
            "base_url": normalize_openai_base(preset.get("default_url") or url),
            "reachable": True,
            "models": models,
        }
    return {
        "id": preset["id"],
        "label": preset["label"],
        "base_url": preset["default_url"],
        "reachable": False,
        "models": [],
        "error": last_error,
    }


def scan_local_endpoints(
    extra_urls: list[str] | None = None,
    *,
    timeout: float = 0.6,
    probe: ProbeFn | None = None,
) -> list[dict[str, Any]]:
    """Scan well-known local ports. Does not contact Hugging Face or the WAN."""
    do_probe = probe or (lambda url, t, headers: http_json(url, timeout=t, headers=headers))
    found: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_probe_preset, preset, do_probe, timeout): preset["id"]
            for preset in LOCAL_PRESETS
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                found.append(result)
    order = {item["id"]: index for index, item in enumerate(LOCAL_PRESETS)}
    found.sort(key=lambda item: order.get(item["id"], 99))

    for raw in extra_urls or []:
        url = assert_local_or_lan_url(raw)
        try:
            models = list_local_models(url, probe=do_probe, timeout=timeout)
            found.append({
                "id": "custom",
                "label": "Custom",
                "base_url": normalize_openai_base(url),
                "reachable": True,
                "models": models,
            })
        except Exception as exc:  # noqa: BLE001
            found.append({
                "id": "custom",
                "label": "Custom",
                "base_url": url,
                "reachable": False,
                "models": [],
                "error": str(exc),
            })
    return found


def _windows_hidden() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0), "startupinfo": startup}


def _known_executable(name: str, candidates: list[Path]) -> Path | None:
    found = shutil.which(name)
    if found:
        return Path(found)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _command_json(command: list[str], *, timeout: int = 20) -> Any:
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, **_windows_hidden(),
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    raw = result.stdout.strip()
    return json.loads(raw) if raw else None


def _model_files(root: Path, *, limit: int = 100) -> list[str]:
    if not root.is_dir():
        return []
    results: list[str] = []
    extensions = {".gguf", ".bin", ".safetensors", ".onnx", ".pth", ".pt"}
    try:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in extensions:
                results.append(str(path))
                if len(results) >= limit:
                    break
    except OSError:
        pass
    return results


def _memory_fit_label(model_bytes: int, available_bytes: int) -> str:
    """Return conservative, informational fit guidance for a model artifact."""
    if model_bytes <= 0 or available_bytes <= 0:
        return "unknown"
    if model_bytes > available_bytes:
        return "insufficient"
    if model_bytes > available_bytes * 0.65:
        return "tight"
    return "comfortable"


def _runtime_resource_snapshot(
    runtime_id: str,
    model_files: list[str],
    cli_models: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure local model storage and resident runtime memory without loading a model."""
    file_sizes: list[int] = []
    for value in model_files:
        try:
            file_sizes.append(Path(value).stat().st_size)
        except OSError:
            continue
    reported_sizes: list[int] = []
    for model in cli_models:
        for key in ("size", "sizeBytes", "size_bytes", "file_size"):
            try:
                size = int(model.get(key) or 0)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                reported_sizes.append(size)
                break

    sizes = file_sizes + reported_sizes

    result: dict[str, Any] = {
        # A runtime may report the same artifacts that were found on disk.
        "model_storage_bytes": max(sum(file_sizes), sum(reported_sizes)),
        "largest_model_bytes": max(sizes, default=0),
        "resident_memory_bytes": 0,
        "running_processes": [],
        "system_available_memory_bytes": 0,
        "system_total_memory_bytes": 0,
        "fit": "unknown",
        "fit_is_estimate": True,
    }
    try:
        import psutil
    except ImportError:
        return result

    memory = psutil.virtual_memory()
    result["system_available_memory_bytes"] = int(memory.available)
    result["system_total_memory_bytes"] = int(memory.total)
    tokens = {
        "ollama": ("ollama",),
        "lmstudio": ("lm studio", "lmstudio", "lms"),
        "jan": ("jan",),
        "gpt4all": ("gpt4all",),
        "llamacpp": ("llama-server", "llama server"),
        "koboldcpp": ("koboldcpp",),
    }.get(runtime_id, ())
    for process in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            info = process.info
            name = str(info.get("name") or "").lower()
            command = " ".join(str(value) for value in (info.get("cmdline") or [])).lower()
            exact_name = Path(name).stem
            matched = any(
                token == exact_name if len(token) <= 3
                else (token in command or token in name or token == exact_name)
                for token in tokens
            )
            if not matched:
                continue
            rss = int(getattr(info.get("memory_info"), "rss", 0) or 0)
            result["resident_memory_bytes"] += rss
            result["running_processes"].append({"pid": int(info["pid"]), "name": info.get("name"), "rss_bytes": rss})
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    result["running_processes"] = result["running_processes"][:50]
    result["fit"] = _memory_fit_label(result["largest_model_bytes"], int(memory.available))
    return result


def discover_installed_runtimes() -> list[dict[str, Any]]:
    """Inventory known local model applications and on-disk model stores.

    This does not execute model files or contact the internet. CLI JSON is used
    when a known local application provides it; otherwise only paths are read.
    """
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    programs = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    specs = [
        {
            "id": "ollama", "label": "Ollama", "command": "ollama",
            "executables": [local / "Programs" / "Ollama" / "ollama.exe", programs / "Ollama" / "ollama.exe"],
            "model_dirs": [home / ".ollama" / "models"],
        },
        {
            "id": "lmstudio", "label": "LM Studio", "command": "lms",
            "executables": [home / ".lmstudio" / "bin" / "lms.exe", local / "LM-Studio" / "bin" / "lms.exe"],
            "model_dirs": [home / ".lmstudio" / "models", home / ".cache" / "lm-studio" / "models"],
        },
        {
            "id": "jan", "label": "Jan", "command": "jan",
            "executables": [local / "Programs" / "jan" / "Jan.exe", local / "Programs" / "Jan" / "Jan.exe"],
            "model_dirs": [home / ".jan" / "models", home / "jan" / "models"],
        },
        {
            "id": "gpt4all", "label": "GPT4All", "command": "gpt4all",
            "executables": [local / "nomic.ai" / "GPT4All" / "GPT4All.exe", programs / "GPT4All" / "GPT4All.exe"],
            "model_dirs": [home / ".cache" / "gpt4all", local / "nomic.ai" / "GPT4All"],
        },
        {
            "id": "llamacpp", "label": "llama.cpp", "command": "llama-server",
            "executables": [home / "llama.cpp" / "llama-server.exe", local / "llama.cpp" / "llama-server.exe"],
            "model_dirs": [],
        },
        {
            "id": "koboldcpp", "label": "KoboldCpp", "command": "koboldcpp",
            "executables": [home / "KoboldCpp" / "koboldcpp.exe", local / "KoboldCpp" / "koboldcpp.exe"],
            "model_dirs": [],
        },
    ]
    inventory: list[dict[str, Any]] = []
    for spec in specs:
        executable = _known_executable(str(spec["command"]), list(spec["executables"]))
        model_files: list[str] = []
        cli_models: list[dict[str, Any]] = []
        if spec["id"] == "lmstudio" and executable:
            try:
                payload = _command_json([str(executable), "ls", "--json"])
                if isinstance(payload, list):
                    cli_models = [item for item in payload if isinstance(item, dict)]
            except Exception:
                pass
        elif spec["id"] == "ollama" and executable:
            try:
                payload = _command_json([str(executable), "list", "--json"])
                if isinstance(payload, list):
                    cli_models = [item for item in payload if isinstance(item, dict)]
            except Exception:
                pass
        for directory in spec["model_dirs"]:
            model_files.extend(_model_files(Path(directory), limit=max(0, 100 - len(model_files))))
            if len(model_files) >= 100:
                break
        installed = bool(executable or cli_models or model_files or any(Path(path).exists() for path in spec["model_dirs"]))
        if not installed:
            continue
        inventory.append({
            "id": spec["id"], "label": spec["label"], "installed": True,
            "executable": str(executable) if executable else "",
            "models": cli_models,
            "model_files": model_files,
            "resources": _runtime_resource_snapshot(str(spec["id"]), model_files, cli_models),
        })

    # Hugging Face caches can be consumed by several runtimes, so report them
    # independently without pretending a cache is itself a reachable server.
    hf_root = home / ".cache" / "huggingface" / "hub"
    hf_models = []
    if hf_root.is_dir():
        try:
            hf_models = [path.name for path in hf_root.iterdir() if path.is_dir() and path.name.startswith("models--")][:100]
        except OSError:
            pass
    if hf_models:
        inventory.append({
            "id": "huggingface-cache", "label": "Hugging Face model cache", "installed": True,
            "executable": "", "models": [{"modelKey": name.replace("models--", "").replace("--", "/")} for name in hf_models],
            "model_files": [],
            "resources": _runtime_resource_snapshot("huggingface-cache", [], []),
        })
    return inventory


def _runtime_model_key(runtime: dict[str, Any]) -> str:
    for model in runtime.get("models") or []:
        if not isinstance(model, dict) or model.get("type") == "embedding":
            continue
        value = model.get("modelKey") or model.get("key") or model.get("name") or model.get("model")
        if value:
            return str(value)
    return ""


def _start_known_runtime(runtime: dict[str, Any]) -> None:
    executable = str(runtime.get("executable") or "")
    if not executable:
        return
    runtime_id = runtime.get("id")
    if runtime_id == "lmstudio":
        subprocess.run([executable, "server", "start"], capture_output=True, timeout=45, **_windows_hidden())
        model = _runtime_model_key(runtime)
        if model:
            subprocess.run(
                [executable, "load", model, "--yes"], capture_output=True, timeout=300,
                **_windows_hidden(),
            )
    elif runtime_id == "ollama":
        subprocess.Popen(
            [executable, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, **_windows_hidden(),
        )


def discover_local_environment(
    extra_urls: list[str] | None = None,
    *,
    auto_start: bool = False,
    timeout: float = 0.6,
) -> dict[str, Any]:
    """Find installed runtimes and connectable local endpoints.

    When ``auto_start`` is true, only recognized Ollama/LM Studio executables
    are launched, and both remain bound to their own localhost defaults.
    """
    runtimes = discover_installed_runtimes()
    endpoints = scan_local_endpoints(extra_urls, timeout=timeout)
    if auto_start and not any(item.get("reachable") and item.get("models") for item in endpoints):
        for runtime in runtimes:
            if runtime.get("id") not in {"ollama", "lmstudio"}:
                continue
            try:
                _start_known_runtime(runtime)
            except Exception:
                continue
            for _ in range(20):
                time.sleep(0.25)
                endpoints = scan_local_endpoints(extra_urls, timeout=max(timeout, 0.8))
                if any(item.get("reachable") and item.get("models") for item in endpoints):
                    break
            if any(item.get("reachable") and item.get("models") for item in endpoints):
                break
    selected = next((item for item in endpoints if item.get("reachable") and item.get("models")), None)
    return {
        "runtimes": runtimes,
        "endpoints": endpoints,
        "selected": selected,
        "auto_started": bool(auto_start and selected),
    }
