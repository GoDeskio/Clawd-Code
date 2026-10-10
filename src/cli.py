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
  clawd memory list        List local memories for this user
  clawd memory delete <id> Delete one local memory
  clawd cron list          List local scheduled jobs
  clawd cron run <id>      Run one scheduled job now
  clawd voice settings     Show local speech settings
  clawd kb add <path>      Index a local PDF, DOCX, MD, TXT, or HTML file
  clawd kb search <query>  Search local documents and cite the passage
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

    memory_parser = subparsers.add_parser('memory', help='List, recall, or delete local memories')
    memory_sub = memory_parser.add_subparsers(dest='memory_command')
    memory_sub.add_parser('list', help='List memories stored for this user')
    recall_parser = memory_sub.add_parser('recall', help='Find memories that match text')
    recall_parser.add_argument('query', nargs='+')
    delete_parser = memory_sub.add_parser('delete', help='Delete one memory by id')
    delete_parser.add_argument('memory_id')

    cron_parser = subparsers.add_parser('cron', help='List, run, enable, disable, or delete local schedules')
    cron_sub = cron_parser.add_subparsers(dest='cron_command')
    cron_sub.add_parser('list', help='List scheduled jobs for this user')
    cron_run = cron_sub.add_parser('run', help='Run one job now')
    cron_run.add_argument('job_id')
    cron_enable = cron_sub.add_parser('enable', help='Enable a job')
    cron_enable.add_argument('job_id')
    cron_disable = cron_sub.add_parser('disable', help='Disable a job')
    cron_disable.add_argument('job_id')
    cron_delete = cron_sub.add_parser('delete', help='Delete a job')
    cron_delete.add_argument('job_id')
    cron_logs = cron_sub.add_parser('logs', help='Show scheduler logs')
    cron_logs.add_argument('job_id', nargs='?')

    voice_parser = subparsers.add_parser('voice', help='Local speech, push-to-talk, and devices')
    voice_parser.add_argument('words', nargs='*', help='settings, devices, stt, tts, ptt, wake, say')

    kb_parser = subparsers.add_parser('kb', help='Add, list, remove, or search the local document index')
    kb_sub = kb_parser.add_subparsers(dest='kb_command')
    kb_add = kb_sub.add_parser('add', help='Index a local document')
    kb_add.add_argument('path')
    kb_sub.add_parser('list', help='List indexed documents')
    kb_remove = kb_sub.add_parser('remove', help='Remove one document by id')
    kb_remove.add_argument('doc_id')
    kb_search = kb_sub.add_parser('search', help='Search indexed documents')
    kb_search.add_argument('query', nargs='+')

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
    elif args.command == 'memory':
        return handle_memory(args)
    elif args.command == 'cron':
        return handle_cron(args)
    elif args.command == 'voice':
        return handle_voice(args)
    elif args.command == 'kb':
        return handle_kb(args)

    # Default: start REPL
    return start_repl(stream=args.stream)


def _show_provider_defaults_table() -> None:
    """Print a table showing available providers and their defaults."""
    from src.providers import visible_provider_info

    console = Console()
    table = Table(title="Available Providers & Defaults", show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("Provider", style="cyan")
    table.add_column("Default Model", style="magenta")
    table.add_column("Base URL", style="green")

    for name, info in visible_provider_info().items():
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


def handle_memory(args) -> int:
    """List, recall, or delete memories stored on this machine."""
    from src.agent.memory import format_memory_command

    action = getattr(args, "memory_command", None) or "list"
    if action == "recall":
        text = format_memory_command("recall " + " ".join(args.query))
    elif action == "delete":
        text = format_memory_command("delete " + args.memory_id)
    else:
        text = format_memory_command("list")
    print(text)
    if action == "delete" and text.startswith("No memory"):
        return 1
    return 0


def handle_cron(args) -> int:
    """List, run, enable, disable, or delete schedules stored on this machine."""
    from src.scheduler.service import format_cron_command

    action = getattr(args, "cron_command", None) or "list"
    job_id = getattr(args, "job_id", None) or ""
    if action == "logs" and not job_id:
        text = format_cron_command("logs")
    elif action == "list":
        text = format_cron_command("list")
    else:
        text = format_cron_command(f"{action} {job_id}".strip())
    print(text)
    if text.startswith("No job"):
        return 1
    return 0


def handle_voice(args) -> int:
    """Show or change speech settings stored on this machine."""
    from src.voice.service import format_voice_command

    words = getattr(args, "words", None) or []
    print(format_voice_command(" ".join(words)))
    return 0


def handle_kb(args) -> int:
    """Add, list, remove, or search documents stored on this machine."""
    from src.knowledge.service import format_kb_command

    action = getattr(args, "kb_command", None) or "list"
    if action == "add":
        text = format_kb_command("add " + args.path)
    elif action == "remove":
        text = format_kb_command("remove " + args.doc_id)
    elif action == "search":
        text = format_kb_command("search " + " ".join(args.query))
    elif action == "list":
        text = format_kb_command("list")
    else:
        text = format_kb_command("")
    print(text)
    if text.startswith("No document") or text.startswith("document not found"):
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
