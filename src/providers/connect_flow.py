"""Interactive provider connect used by `clawd login` and desktop-equivalent CLI."""

from __future__ import annotations

from typing import Any

from src.config import set_api_key, set_default_provider
from src.providers import PROVIDER_INFO
from src.providers.huggingface_connect import verify_huggingface_token
from src.providers.local_endpoints import list_local_models, scan_local_endpoints


def save_provider_connection(
    provider: str,
    *,
    api_key: str = "",
    base_url: str | None = None,
    default_model: str | None = None,
) -> None:
    if provider not in PROVIDER_INFO:
        raise ValueError(f"Unknown provider: {provider}")
    info = PROVIDER_INFO[provider]
    url = base_url or info["default_base_url"]
    model = default_model if default_model is not None else info["default_model"]
    if info.get("kind") == "local":
        from src.providers.local_endpoints import normalize_openai_base

        url = normalize_openai_base(url)
        if not str(model or "").strip():
            raise ValueError("Pick a local model before connecting")
    if info.get("requires_key", True) and not str(api_key or "").strip():
        raise ValueError(f"{info.get('token_label') or 'API key'} cannot be empty")
    set_api_key(
        provider,
        api_key=api_key,
        base_url=url,
        default_model=model,
    )
    set_default_provider(provider)


def prompt_provider_connection(console: Any, *, default: str = "anthropic") -> int:
    """Rich-prompted connect. Returns 0 on success."""
    from rich.prompt import Prompt

    provider_names = list(PROVIDER_INFO.keys())
    provider = Prompt.ask("Select LLM provider", choices=provider_names, default=default if default in provider_names else "anthropic")
    info = PROVIDER_INFO[provider]

    if provider == "local":
        return _prompt_local(console, Prompt, info)
    if provider == "huggingface":
        return _prompt_huggingface(console, Prompt, info)

    api_key = Prompt.ask(f"Enter {info.get('token_label') or 'API key'}", password=True)
    if not api_key:
        console.print("\n[red]Error: API key cannot be empty[/red]")
        return 1
    console.print(f"\n[dim]Default:[/dim] {info['default_base_url']}")
    base_url = Prompt.ask("Base URL", default=info["default_base_url"])
    models = ", ".join(info.get("available_models") or [])
    if models:
        console.print(f"\n[dim]Available models:[/dim] {models}")
    default_model = Prompt.ask("Default model", default=info["default_model"])
    save_provider_connection(provider, api_key=api_key, base_url=base_url, default_model=default_model)
    console.print(f"\n[green]✓ {info['label']} saved. Switching providers does not require a reinstall.[/green]\n")
    return 0


def _prompt_huggingface(console: Any, Prompt: Any, info: dict[str, Any]) -> int:
    console.print(info.get("help") or "")
    token = Prompt.ask("Hugging Face token (hf_…)", password=True)
    if not token:
        console.print("\n[red]Error: Hugging Face token cannot be empty[/red]")
        return 1
    test = Prompt.ask("Test the connection now?", choices=["y", "n"], default="y")
    if test == "y":
        try:
            result = verify_huggingface_token(token)
            console.print(f"[green]✓ {result.get('message')}[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Connection test failed: {exc}[/red]")
            return 1
    console.print(f"\n[dim]Inference router:[/dim] {info['default_base_url']}")
    console.print(f"[dim]Suggested models:[/dim] {', '.join(info.get('available_models') or [])}")
    model = Prompt.ask("Default Hub model (org/name)", default=info["default_model"])
    save_provider_connection("huggingface", api_key=token, base_url=info["default_base_url"], default_model=model)
    console.print("\n[green]✓ Hugging Face connected. Token stored only in ~/.clawd/config.json (mode 0600).[/green]\n")
    return 0


def _prompt_local(console: Any, Prompt: Any, info: dict[str, Any]) -> int:
    console.print(info.get("help") or "")
    console.print("Scanning common local ports (loopback only)…")
    endpoints = scan_local_endpoints()
    reachable = [item for item in endpoints if item.get("reachable")]
    if reachable:
        for item in reachable:
            models = ", ".join(item.get("models") or []) or "(no models listed)"
            console.print(f"  [cyan]{item['label']}[/cyan]  {item['base_url']}  {models}")
    else:
        console.print("[dim]No local servers answered. You can still enter a loopback/LAN URL.[/dim]")

    default_url = reachable[0]["base_url"] if reachable else info["default_base_url"]
    base_url = Prompt.ask("Local base URL", default=default_url)
    api_key = Prompt.ask("Optional API key (Enter to skip)", default="")
    models: list[str] = []
    try:
        models = list_local_models(base_url, api_key)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[dim]Could not list models yet: {exc}[/dim]")
    if models:
        console.print(f"[dim]Available:[/dim] {', '.join(models)}")
    default_model = models[0] if models else ""
    model = Prompt.ask("Default local model", default=default_model or "llama3.2")
    save_provider_connection("local", api_key=api_key, base_url=base_url, default_model=model)
    console.print("\n[green]✓ Local LLM saved. Endpoint stays on loopback/LAN.[/green]\n")
    return 0
