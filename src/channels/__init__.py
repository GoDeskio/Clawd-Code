"""Local chat-channel bridge for Telegram, Discord, and Slack.

The shape follows Octop's gateway: one inbound message, an allow-list, and a
reply sent back on the same channel. Jonathan Ai does not include the
upstream CN channels and does not import octop-gateway.
"""

from src.channels.service import format_channels_command, route_inbound

__all__ = ["format_channels_command", "route_inbound"]
