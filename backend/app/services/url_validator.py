"""Fetch untrusted mint links with pinned public DNS and a strict byte cap."""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import aiohttp

MAX_URL_LENGTH = 2048
MAX_RESPONSE_BYTES = 512 * 1024
REQUEST_TIMEOUT_SECONDS = 5.0
MAX_REDIRECTS = 3


class URLSecurityError(Exception):
    pass


def is_ip_private_or_restricted(ip_str: str) -> bool:
    try:
        return not ipaddress.ip_address(ip_str).is_global
    except ValueError:
        return True


def _validated_destination(url: str):
    if not url or len(url) > MAX_URL_LENGTH:
        raise URLSecurityError("URL is missing or exceeds maximum allowable length.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLSecurityError(f"Unsupported URL scheme: {parsed.scheme}. Only HTTP/HTTPS permitted.")
    hostname = parsed.hostname
    if not hostname:
        raise URLSecurityError("Missing hostname in URL.")
    if parsed.username or parsed.password:
        raise URLSecurityError("URL credentials are not permitted.")
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "metadata.google.internal"):
        raise URLSecurityError(f"Prohibited hostname: {hostname}")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except (socket.gaierror, ValueError) as exc:
        raise URLSecurityError(f"DNS resolution failed for {hostname}: {exc}") from exc
    if not addresses:
        raise URLSecurityError(f"DNS resolution returned no address for {hostname}.")
    for address in addresses:
        ip = address[4][0]
        if is_ip_private_or_restricted(ip):
            raise URLSecurityError(f"Destination IP {ip} for host {hostname} is restricted (private/loopback/metadata).")
    return hostname, port, addresses


def validate_safe_url(url: str) -> str:
    _validated_destination(url)
    return url


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, hostname, port, addresses):
        self.hostname = hostname
        self.port = port
        self.addresses = addresses

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host != self.hostname or port != self.port:
            raise URLSecurityError("Unexpected destination during connection.")
        return [dict(hostname=host, host=address[4][0], port=port,
                     family=address[0], proto=address[2], flags=0)
                for address in self.addresses]

    async def close(self):
        pass


async def fetch_safe_url(url: str) -> str:
    current = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        hostname, port, addresses = _validated_destination(current)
        connector = aiohttp.TCPConnector(
            resolver=_PinnedResolver(hostname, port, addresses),
            use_dns_cache=False, force_close=True,
        )
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout,
                                         trust_env=False, auto_decompress=False) as client:
            async with client.get(current, allow_redirects=False) as response:
                if 300 <= response.status < 400:
                    if redirect_count == MAX_REDIRECTS:
                        raise URLSecurityError(f"Exceeded maximum allowed redirects ({MAX_REDIRECTS}).")
                    location = response.headers.get("Location")
                    if not location:
                        raise URLSecurityError("Redirect missing Location header.")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > MAX_RESPONSE_BYTES:
                            raise URLSecurityError("Response exceeds maximum allowed size.")
                    except ValueError as exc:
                        raise URLSecurityError("Invalid Content-Length header.") from exc
                body = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise URLSecurityError("Downloaded body exceeds maximum allowed size.")
                return body.decode(response.charset or "utf-8", errors="replace")
    raise URLSecurityError("Redirect limit exceeded.")
