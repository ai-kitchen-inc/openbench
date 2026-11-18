"""SSRF guard for server-side HTTP fetches.

Any URL that reaches the server from a chat user, an uploaded document, or
an LLM tool argument must be treated as attacker-controlled: left unchecked
it can point the server at loopback services, the private network, or the
cloud metadata endpoint (169.254.169.254) and read the response back.

Two entry points:

* :func:`validate_public_url` — accept only ``http(s)`` URLs whose host is a
  public address (every address a hostname resolves to must be public).
* :func:`safe_get` — fetch a URL with redirects followed manually so *every*
  hop is re-validated, and with the response body capped.

The guard is resolve-then-fetch, so a DNS answer that changes between the
check and the connection (DNS rebinding) is not covered; callers that need
that guarantee must pin the resolved address themselves.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

#: Reason codes returned by :func:`blocked_host_reason`.
BLOCK_INVALID = "invalid"
BLOCK_LOCAL = "local"
BLOCK_PRIVATE = "private"

DEFAULT_MAX_URL_CHARS = 8192
DEFAULT_MAX_REDIRECTS = 5

_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata"}

_MESSAGES = {
    BLOCK_INVALID: "URL must be a valid http or https URL.",
    BLOCK_LOCAL: "Local URLs are not allowed.",
    BLOCK_PRIVATE: "Local or private network URLs are not allowed.",
}


def is_public_ip(address: str) -> bool:
    """Return True when ``address`` is a publicly routable IP literal."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )


def blocked_host_reason(host: str) -> str | None:
    """Return a ``BLOCK_*`` code when ``host`` may not be fetched, else None.

    Rejects loopback/private/link-local literals (including the cloud
    metadata endpoint and alternate spellings such as ``127.1``,
    ``2130706433`` or ``0x7f000001``, which ``ipaddress`` does not parse but
    the OS resolver does) and hostnames that resolve to such addresses.
    Resolution failure is not a block: the fetch will fail on its own.
    """
    if not host:
        return BLOCK_INVALID
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return BLOCK_LOCAL
    literal = host.strip("[]")
    try:
        ipaddress.ip_address(literal)
    except ValueError:
        pass
    else:
        return None if is_public_ip(literal) else BLOCK_PRIVATE
    # Shorthand / integer / hex IPv4 forms are not ip_address() literals but
    # every libc resolver accepts them; normalise through inet_aton first.
    try:
        dotted = socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        dotted = None
    if dotted is not None:
        return None if is_public_ip(dotted) else BLOCK_PRIVATE
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None
    for info in infos:
        if not is_public_ip(info[4][0]):
            return BLOCK_PRIVATE
    return None


def validate_public_url(url: str, *, max_chars: int = DEFAULT_MAX_URL_CHARS) -> str:
    """Return the stripped URL, or raise ``ValueError`` for unsafe targets."""
    value = (url or "").strip()
    if len(value) > max_chars:
        raise ValueError("URL is too long.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(_MESSAGES[BLOCK_INVALID])
    reason = blocked_host_reason((parsed.hostname or "").lower())
    if reason:
        raise ValueError(_MESSAGES[reason])
    return value


@dataclass(frozen=True)
class FetchResult:
    """Outcome of :func:`safe_get`."""

    content: bytes
    content_type: str
    final_url: str
    status_code: int
    encoding: str | None
    truncated: bool


def safe_get(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    truncate: bool = False,
) -> FetchResult:
    """GET ``url`` with every redirect hop re-validated and the body capped.

    Args:
        url: Target URL; validated with :func:`validate_public_url`.
        max_bytes: Maximum response body size.
        timeout: Per-request timeout in seconds.
        headers: Extra request headers.
        max_redirects: Maximum number of redirects to follow.
        truncate: When True a body longer than ``max_bytes`` is cut and
            ``FetchResult.truncated`` is set; when False it raises.

    Raises:
        ValueError: Unsafe URL or redirect target, too many redirects, or
            (with ``truncate=False``) an oversized body.
        requests.RequestException: Transport or HTTP status errors.
    """
    import requests

    current = validate_public_url(url)
    with requests.Session() as session:
        for _hop in range(max_redirects + 1):
            response = session.get(
                current,
                timeout=timeout,
                headers=headers,
                allow_redirects=False,
                stream=True,
            )
            try:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("location", "")
                    if not location:
                        raise ValueError("Redirect has no target.")
                    current = validate_public_url(urljoin(current, location))
                    continue
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                chunks: list[bytes] = []
                total = 0
                truncated = False
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    if total + len(chunk) > max_bytes:
                        if not truncate:
                            raise ValueError(f"Response exceeds the {max_bytes} byte limit.")
                        chunks.append(chunk[: max_bytes - total])
                        truncated = True
                        break
                    total += len(chunk)
                    chunks.append(chunk)
                return FetchResult(
                    content=b"".join(chunks),
                    content_type=content_type,
                    final_url=current,
                    status_code=response.status_code,
                    encoding=response.encoding,
                    truncated=truncated,
                )
            finally:
                response.close()
    raise ValueError("Too many redirects.")
