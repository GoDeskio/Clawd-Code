"""Desktop host for Clawd Code.

The existing Python agent loop, tools, skills, providers, and sessions stay
the brain. This package adds a localhost HTTP/SSE host and a static UI that
Electron (or a browser) can wrap.
"""

from .runtime import DesktopRuntime
from .server import DesktopServer, create_server

__all__ = ["DesktopRuntime", "DesktopServer", "create_server"]
