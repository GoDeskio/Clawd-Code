"""CLI entry point for Clawd Codex."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table


def main():
    """CLI main entry point."""
    # Quick path for --version
    if len(sys.argv) == 2 and sys.argv[1] in ['--version', '-v', '-V']:
        from src import __version__
        print(f"clawd-codex version {__version__} (Python)")
        return 0

    parser = argparse.ArgumentParser(
        description="Jonathan Ai - local desktop and CLI agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  clawd --version          Show version
  clawd login              Configure API keys
  clawd config             Show current configuration
  clawd --stream           Start REPL with live response rendering
  clawd desktop            Start the desktop host (browser UI)
  clawd install            First-run wizard (source + deps)
  clawd update             Check/apply GoDeskio/Clawd-Code updates
  clawd                    Start interactive REPL
"""
    )

    parser.add_argument(
        '--version',
        action='store_true',
        help='Show version information'
    )
    parser.add_argument(
        '--config',
        action='store_true',
        help='Show current configuration'
    )
    parser.add_argument(
        '--stream',
        action='store_true',
        help='Enable live response rendering in the REPL'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # login subcommand
    login_parser = subparsers.add_parser('login', help='Configure API keys')

    # config subcommand
    config_parser = subparsers.add_parser('config', help='Show current configuration')

    desktop_parser = subparsers.add_parser('desktop', help='Start the desktop host / UI backend')
    desktop_parser.add_argument('--host', default='127.0.0.1', help='Bind host (localhost only)')
    desktop_parser.add_argument('--port', type=int, default=8765, help='Bind port')
    desktop_parser.add_argument('--workspace', default=None, help='Initial workspace directory')
    desktop_parser.add_argument('--token', default=None, help='API token for the local UI')
    desktop_parser.add_argument('--no-browser', action='store_true', help='Do not open a browser window')

    install_parser = subparsers.add_parser('install', help='First-run install wizard')
    install_parser.add_argument('--source-dir', default=None, help='Local source folder (default: ~/Jonathan/Jonathan-Ai)')
    install_parser.add_argument('--from-local', default=None, help='Copy this checkout instead of cloning')
    install_parser.add_argument('--clone', action='store_true', help='Always clone from GoDeskio/Clawd-Code')
    install_parser.add_argument('--skip-desktop-deps', action='store_true')
    install_parser.add_argument('--cli', action='store_true')
    install_parser.add_argument('--yes', action='store_true')
    install_parser.add_argument('--ui', action='store_true')
    install_parser.add_argument('--launch', action='store_true')
    install_parser.add_argument('--no-browser', action='store_true')

    update_parser = subparsers.add_parser('update', help='Check or apply updates from GoDeskio/Clawd-Code')
    update_parser.add_argument('--apply', action='store_true', help='Fetch and apply if an update is available')
    update_parser.add_argument('--source-dir', default=None)

    args = parser.parse_args()

    # Handle --version
    if args.version:
        from src import __version__
        print(f"clawd-codex version {__version__} (Python)")
        return 0

    # Handle --config
    if args.config:
        return show_config()

    # Handle commands
    if args.command == 'login':
        return handle_login()
    elif args.command == 'config':
        return show_config()
    elif args.command == 'desktop':
        try:
            from src.install.bootstrap import ensure_runtime_deps

            ensure_runtime_deps()
        except Exception:
            pass
        from src.desktop.server import run_desktop
        return run_desktop(
            host=args.host,
            port=args.port,
            workspace=args.workspace,
            open_browser=not args.no_browser,
            token=args.token,
        )
    elif args.command == 'install':
        from src.install.__main__ import main as install_main
        from src.install.source import default_source_dir
        argv = []
        if args.source_dir:
            argv.extend(["--source-dir", args.source_dir])
        else:
            argv.extend(["--source-dir", str(default_source_dir())])
        if args.from_local:
            argv.extend(["--from-local", args.from_local])
        if args.clone:
            argv.append("--clone")
        if args.skip_desktop_deps:
            argv.append("--skip-desktop-deps")
        if args.cli:
            argv.append("--cli")
        if args.yes:
            argv.append("--yes")
        if args.ui:
            argv.append("--ui")
        if args.launch:
            argv.append("--launch")
        if args.no_browser:
            argv.append("--no-browser")
        return install_main(argv)
    elif args.command == 'update':
        from src.update import Updater
        updater = Updater(args.source_dir)
        if args.apply:
            result = updater.apply()
            print(f"Updated to {result.get('sha')} in {result.get('source_dir')}")
            return 0
        status = updater.status(refresh=True)
        if status.get("error"):
            print(f"Update check failed: {status['error']}")
            return 1
        state = "available" if status.get("update_available") else "up to date"
        print(f"GoDeskio/Clawd-Code: {state}")
        print(f"local  {status.get('local_sha')}")
        print(f"remote {status.get('remote_sha')}")
        return 0

    # Default: start REPL
    return start_repl(stream=args.stream)


def _show_provider_defaults_table() -> None:
    """Print a table showing available providers and their defaults."""
    from src.providers import PROVIDER_INFO

    console = Console()
    table = Table(title="Available Providers & Defaults", show_header=True, header_style="bold")
    table.add_column("Provider", style="cyan")
    table.add_column("Default Model", style="magenta")
    table.add_column("Base URL", style="green")

    for name, info in PROVIDER_INFO.items():
        table.add_row(
            f"{name} ({info['label']})",
            info["default_model"],
            info["default_base_url"],
        )

    console.print(table)
    console.print()


def handle_login():
    """Interactive API configuration."""
    console = Console()
    console.print("\n[bold blue]Jonathan Ai - API Configuration[/bold blue]\n")

    # Show available providers and their defaults
    _show_provider_defaults_table()

    from src.providers.connect_flow import prompt_provider_connection

    return prompt_provider_connection(console, default="anthropic")


def show_config():
    """Show current configuration."""
    console = Console()

    try:
        from src.config import load_config, get_config_path

        config = load_config()
        config_path = get_config_path()

        console.print(f"\n[bold]Configuration File:[/bold] {config_path}\n")
        console.print("[bold]Current Configuration:[/bold]\n")

        # Show default provider
        console.print(f"[cyan]Default Provider:[/cyan] {config.get('default_provider', 'Not set')}")

        # Show providers (without showing full API keys)
        console.print("\n[cyan]Configured Providers:[/cyan]")
        for provider_name, provider_config in config.get("providers", {}).items():
            api_key = provider_config.get("api_key", "")
            masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "Not set"

            console.print(f"\n  [yellow]{provider_name.upper()}:[/yellow]")
            console.print(f"    API Key: {masked_key}")
            console.print(f"    Base URL: {provider_config.get('base_url', 'Not set')}")
            console.print(f"    Default Model: {provider_config.get('default_model', 'Not set')}")

        console.print()

    except Exception as e:
        console.print(f"\n[red]Error loading configuration: {e}[/red]\n")
        return 1

    return 0


def start_repl(stream: bool = False):
    """Start interactive REPL."""
    from src.config import get_default_provider
    from src.repl import ClawdREPL

    provider = get_default_provider()
    repl = ClawdREPL(provider_name=provider, stream=stream)
    repl.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
