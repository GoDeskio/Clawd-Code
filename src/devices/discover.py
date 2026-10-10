"""Read-only LAN discovery: ARP table, SSDP responses, and mDNS answers.

ARP is read from the neighbor table. SSDP and mDNS parsers do not send
traffic; the optional probe helpers are the only writers, and they only
multicast a discovery query.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path

from src.devices.lan import host_is_private_ip

_MAC = re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def parse_arp_table(text: str) -> list[dict[str, str]]:
    """Parse `/proc/net/arp` or `arp -a` text. Public addresses are dropped."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if "IP address" in line or line.lower().startswith("address"):
            continue
        ips = _IPV4.findall(line)
        macs = _MAC.findall(line)
        if not ips:
            continue
        address = ips[0]
        if not host_is_private_ip(address) or address in seen:
            continue
        mac = macs[0].lower() if macs else ""
        if mac == "00:00:00:00:00:00":
            continue
        seen.add(address)
        found.append({"source": "arp", "address": address, "name": "", "detail": mac})
    return found


def build_ssdp_probe() -> bytes:
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        "ST: ssdp:all\r\n"
        "\r\n"
    ).encode("ascii")


def parse_ssdp_response(text: str) -> dict[str, str] | None:
    location = ""
    server = ""
    target = ""
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        name = key.strip().lower()
        if name == "location":
            location = value.strip()
        elif name == "server":
            server = value.strip()
        elif name == "st":
            target = value.strip()
    if not location:
        return None
    from urllib.parse import urlparse

    host = urlparse(location).hostname or ""
    if not host_is_private_ip(host):
        return None
    return {"source": "ssdp", "address": host, "name": target, "detail": server}


def encode_dns_name(name: str) -> bytes:
    out = bytearray()
    for label in name.rstrip(".").split("."):
        raw = label.encode("ascii")
        if not raw or len(raw) > 63:
            raise ValueError("dns label is not valid")
        out.append(len(raw))
        out.extend(raw)
    out.append(0)
    return bytes(out)


def build_mdns_query(name: str = "_services._dns-sd._udp.local") -> bytes:
    header = b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    return header + encode_dns_name(name) + b"\x00\x0c\x00\x01"


def build_mdns_address(name: str, ip: str) -> bytes:
    addr = ipaddress.ip_address(ip)
    rtype = b"\x00\x01" if addr.version == 4 else b"\x00\x1c"
    rdata = addr.packed
    header = b"\x00\x00\x84\x00\x00\x00\x00\x01\x00\x00\x00\x00"
    answer = encode_dns_name(name) + rtype + b"\x00\x01\x00\x00\x00\x78" + len(rdata).to_bytes(2, "big") + rdata
    return header + answer


def _read_name(packet: bytes, offset: int, depth: int = 0) -> tuple[str, int]:
    labels: list[str] = []
    while offset < len(packet) and depth < 8:
        length = packet[offset]
        if length == 0:
            return ".".join(labels), offset + 1
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                break
            pointer = ((length & 0x3F) << 8) | packet[offset + 1]
            rest, _end = _read_name(packet, pointer, depth + 1)
            if rest:
                labels.append(rest)
            return ".".join(labels), offset + 2
        offset += 1
        labels.append(packet[offset : offset + length].decode("ascii", "replace"))
        offset += length
    return ".".join(labels), offset


def parse_mdns_addresses(packet: bytes) -> list[dict[str, str]]:
    if len(packet) < 12:
        return []
    questions = int.from_bytes(packet[4:6], "big")
    answers = int.from_bytes(packet[6:8], "big")
    offset = 12
    for _ in range(questions):
        _name, offset = _read_name(packet, offset)
        offset += 4
    found: list[dict[str, str]] = []
    for _ in range(answers):
        if offset >= len(packet):
            break
        name, offset = _read_name(packet, offset)
        if offset + 10 > len(packet):
            break
        rtype = int.from_bytes(packet[offset : offset + 2], "big")
        rdlen = int.from_bytes(packet[offset + 8 : offset + 10], "big")
        start = offset + 10
        data = packet[start : start + rdlen]
        offset = start + rdlen
        if rtype == 1 and len(data) == 4:
            address = str(ipaddress.IPv4Address(data))
        elif rtype == 28 and len(data) == 16:
            address = str(ipaddress.IPv6Address(data))
        else:
            continue
        if not host_is_private_ip(address):
            continue
        found.append({"source": "mdns", "address": address, "name": name, "detail": ""})
    return found


def discover_from_sources(
    *,
    arp_text: str = "",
    ssdp_texts: list[str] | None = None,
    mdns_packets: list[bytes] | None = None,
) -> list[dict[str, str]]:
    rows = parse_arp_table(arp_text)
    for text in ssdp_texts or []:
        parsed = parse_ssdp_response(text)
        if parsed:
            rows.append(parsed)
    for packet in mdns_packets or []:
        rows.extend(parse_mdns_addresses(packet))
    return rows


def read_arp_text(path: Path | None = None) -> str:
    candidate = path or Path("/proc/net/arp")
    try:
        return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def probe_ssdp(timeout: float = 0.4) -> list[str]:
    """Multicast one SSDP M-SEARCH and collect replies. Failures return nothing."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(build_ssdp_probe(), ("239.255.255.250", 1900))
        found: list[str] = []
        while True:
            try:
                data, _addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            found.append(data.decode("utf-8", errors="replace"))
        return found
    except OSError:
        return []
    finally:
        sock.close()


def probe_mdns(timeout: float = 0.4) -> list[bytes]:
    """Multicast one mDNS query and collect replies. Failures return nothing."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(build_mdns_query(), ("224.0.0.251", 5353))
        found: list[bytes] = []
        while True:
            try:
                data, _addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            found.append(data)
        return found
    except OSError:
        return []
    finally:
        sock.close()
