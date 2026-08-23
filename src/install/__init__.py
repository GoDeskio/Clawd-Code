"""First-run installer for the Jonathan Ai desktop agent."""

from .source import default_source_dir, is_allowed_source_url
from .wizard import InstallWizard

__all__ = ["InstallWizard", "default_source_dir", "is_allowed_source_url"]
