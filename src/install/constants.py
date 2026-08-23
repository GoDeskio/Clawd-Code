"""Install and update constants.

The only permitted application source is this GoDesk fork. Upstream
GPT-AGI/Clawd-Code and any other remote are rejected.
"""

from __future__ import annotations

ALLOWED_OWNER = "godeskio"
ALLOWED_REPO = "clawd-code"
ALLOWED_GITHUB_PATH = "GoDeskio/Clawd-Code"
CANONICAL_HTTPS = "https://github.com/GoDeskio/Clawd-Code.git"
CANONICAL_HTTPS_NO_GIT = "https://github.com/GoDeskio/Clawd-Code"
GITHUB_API_REPO = "https://api.github.com/repos/GoDeskio/Clawd-Code"
JONATHAN_FOLDER_NAME = "Jonathan"
SOURCE_FOLDER_NAME = "Clawd-Code"
INSTALL_RECORD_NAME = "install.json"
USER_AGENT = "Clawd-Code-Installer (GoDeskio/Clawd-Code)"
UPDATE_INTERVAL_S = 6 * 60 * 60
PYTHON_MIN = (3, 10)
