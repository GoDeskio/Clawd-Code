"""Install and update constants.

The only permitted application source is this GoDesk fork. Upstream
GPT-AGI/Clawd-Code and any other remote are rejected.
"""

from __future__ import annotations

# User-visible product name. GitHub repo stays GoDeskio/Clawd-Code.
PRODUCT_NAME = "Jonathan Ai"

ALLOWED_OWNER = "godeskio"
ALLOWED_REPO = "clawd-code"
ALLOWED_GITHUB_PATH = "GoDeskio/Clawd-Code"
CANONICAL_HTTPS = "https://github.com/GoDeskio/Clawd-Code.git"
CANONICAL_HTTPS_NO_GIT = "https://github.com/GoDeskio/Clawd-Code"
GITHUB_API_REPO = "https://api.github.com/repos/GoDeskio/Clawd-Code"
UPDATE_BRANCH = "cursor/desktop-agent-shell-e032"
RAW_GITHUB_ROOT = f"https://raw.githubusercontent.com/GoDeskio/Clawd-Code/{UPDATE_BRANCH}"
JONATHAN_FOLDER_NAME = "Jonathan"
SOURCE_FOLDER_NAME = "Jonathan-Ai"
INSTALL_RECORD_NAME = "install.json"
USER_AGENT = "Clawd-Code-Installer (GoDeskio/Clawd-Code)"
UPDATE_INTERVAL_S = 6 * 60 * 60
PYTHON_MIN = (3, 10)
