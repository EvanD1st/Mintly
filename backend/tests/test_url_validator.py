"""Tests for SSRF prevention, scheme restrictions, and private IP blocking."""

import pytest
from app.services.url_validator import validate_safe_url, is_ip_private_or_restricted, URLSecurityError


def test_ip_restriction_filter():
    """Verifies that private, loopback, link-local, and metadata IPs are flagged restricted."""
    assert is_ip_private_or_restricted("127.0.0.1") is True
    assert is_ip_private_or_restricted("10.0.0.1") is True
    assert is_ip_private_or_restricted("172.16.0.5") is True
    assert is_ip_private_or_restricted("192.168.1.100") is True
    assert is_ip_private_or_restricted("169.254.169.254") is True  # Cloud metadata service
    assert is_ip_private_or_restricted("0.0.0.0") is True
    assert is_ip_private_or_restricted("::1") is True
    assert is_ip_private_or_restricted("fe80::1") is True

    # Public IP should not be restricted
    assert is_ip_private_or_restricted("8.8.8.8") is False
    assert is_ip_private_or_restricted("1.1.1.1") is False


def test_validate_safe_url_schemes():
    """Rejects unsafe schemes like file://, data:, ftp://, etc."""
    with pytest.raises(URLSecurityError, match="Unsupported URL scheme"):
        validate_safe_url("file:///etc/passwd")

    with pytest.raises(URLSecurityError, match="Unsupported URL scheme"):
        validate_safe_url("ftp://ftp.example.com/file")

    with pytest.raises(URLSecurityError, match="Unsupported URL scheme"):
        validate_safe_url("javascript:alert(1)")


def test_validate_safe_url_localhost_and_metadata():
    """Rejects localhost and cloud metadata destinations."""
    with pytest.raises(URLSecurityError, match="Prohibited hostname"):
        validate_safe_url("http://localhost:8000/secret")

    with pytest.raises(URLSecurityError, match="Prohibited hostname"):
        validate_safe_url("http://127.0.0.1:5432")

    with pytest.raises(URLSecurityError, match="Prohibited hostname"):
        validate_safe_url("http://metadata.google.internal/computeMetadata/v1/")
