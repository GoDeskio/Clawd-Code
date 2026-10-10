"""LAN device discovery and allow-listed control.

Adapted from the idea of Octop's gateway MQTT channel, limited to private
and link-local addresses. Jonathan Ai does not import octop-gateway.
"""

from src.devices.service import format_devices_command

__all__ = ["format_devices_command"]
