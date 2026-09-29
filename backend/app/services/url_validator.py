"""SSRF-safe URL validation and client for fetching untrusted mint links."""

import ipaddress
import socket
from urllib.parse import urlparse
import httpx


MAX_URL_LENGTH = 2048
MAX_RESPONSE_BYTES = 512 * 1024  # 512 KB
REQUEST_TIMEOUT_SECONDS = 5.0
MAX_REDIRECTS = 3


class URLSecurityError(Exception):
    """Raised when a URL violates SSRF security boundaries."""
    pass


def is_ip_private_or_restricted(ip_str: str) -> bool:
    """Checks whether an IP address is private, loopback, link-local, or reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local or
            ip.is_reserved or
            ip.is_multicast or
            ip.is_unspecified or
            str(ip) in ("169.254.169.254", "0.0.0.0", "::", "::1")
        )
    except ValueError:
        return True


def validate_safe_url(url: str) -> str:
    """Validates that a URL is safe to fetch and does not resolve to private or cloud-metadata IPs."""
    if not url or len(url) > MAX_URL_LENGTH:
        raise URLSecurityError("URL is missing or exceeds maximum allowable length.")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLSecurityError(f"Unsupported URL scheme: {parsed.scheme}. Only HTTP/HTTPS permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise URLSecurityError("Missing hostname in URL.")

    # Disallow localhost directly
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "metadata.google.internal"):
        raise URLSecurityError(f"Prohibited hostname: {hostname}")

    # Resolve DNS and check all IPs
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise URLSecurityError(f"DNS resolution failed for {hostname}: {e}")

    for family, socktype, proto, canonname, sockaddr in addr_info:
        ip = sockaddr[0]
        if is_ip_private_or_restricted(ip):
            raise URLSecurityError(f"Destination IP {ip} for host {hostname} is restricted (private/loopback/metadata).")

    return url


async def fetch_safe_url(url: str) -> str:
    """Safely fetches a URL with SSRF protection, size caps, and bounded timeouts."""
    current_url = validate_safe_url(url)
    
    transport = httpx.AsyncHTTPTransport(retries=1)
    async with httpx.AsyncClient(transport=transport, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
        redirect_count = 0
        while redirect_count <= MAX_REDIRECTS:
            response = await client.get(current_url)
            
            if response.is_redirect:
                redirect_count += 1
                location = response.headers.get("Location")
                if not location:
                    raise URLSecurityError("Redirect missing Location header.")
                # Resolve relative redirects
                from urllib.parse import urljoin
                next_url = urljoin(current_url, location)
                current_url = validate_safe_url(next_url)
                continue

            # Check response size before loading full body
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                raise URLSecurityError(f"Response size ({content_length} bytes) exceeds limit ({MAX_RESPONSE_BYTES} bytes).")

            body = response.text
            if len(body) > MAX_RESPONSE_BYTES:
                raise URLSecurityError(f"Downloaded body exceeds limit ({MAX_RESPONSE_BYTES} bytes).")

            return body

        raise URLSecurityError(f"Exceeded maximum allowed redirects ({MAX_REDIRECTS}).")
