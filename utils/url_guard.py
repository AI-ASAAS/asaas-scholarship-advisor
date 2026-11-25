"""Shared SSRF & outbound HTTP guard for all server-side URL fetches.

Enforces:
- HTTP/HTTPS scheme only; rejects userinfo (@), backslashes, and control characters.
- Standard ports only (80, 443 unless explicitly allowlisted).
- Rejects literal, decimal, octal, hex, short-form IPv4, IPv6, and IPv4-mapped IPv6
  addresses pointing to loopback, private, link-local, multicast, reserved,
  unspecified, or cloud-metadata ranges.
- Resolves hostnames and validates all returned IPs; pins TCP connections to the
  validated IP via a custom httpcore SyncBackend to defeat DNS rebinding while
  keeping TLS SNI / hostname verification intact.
- Disables automatic redirects and re-validates every redirect hop (max 3 hops).
- Caps response byte size and verifies allowed Content-Type headers.
"""

from __future__ import annotations

import ipaddress
import socket
import typing
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpcore
import httpx

from core.config import settings

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
ResolveFn = Callable[[str, int], List[IPAddress]]

_CLOUD_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}
_FORBIDDEN_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
    "ip6-localhost",
    "ip6-loopback",
}
_FORBIDDEN_SUFFIXES = (".localhost", ".local", ".internal", ".arpa")

_DEFAULT_HTML_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
)

_DEFAULT_CLIENT_HEADERS = {
    "User-Agent": "AsaasScholarshipDiscovery/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class UnsafeURLError(ValueError):
    """Raised when an outbound URL violates SSRF, scheme, port, or size rules."""


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    hostname: str
    port: int
    resolved_ips: Tuple[str, ...]


def _is_forbidden_ip(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        if _is_forbidden_ip(ip.ipv4_mapped):
            return True
    if ip in _CLOUD_METADATA_IPS:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def _parse_obfuscated_ip(hostname: str) -> Optional[IPAddress]:
    """Detect standard, decimal, octal, hex, and shorthand IP literals."""
    stripped = hostname.strip("[]")
    try:
        return ipaddress.ip_address(stripped)
    except ValueError:
        pass

    # Single integer decimal/hex/octal (e.g. 2130706433, 0x7f000001, 017700000001)
    if stripped.isdigit() or stripped.lower().startswith("0x"):
        try:
            num = int(stripped, 0)
            if 0 <= num <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(num)
        except ValueError:
            pass

    # Legacy inet_aton parses octal (0177.0.0.1), hex (0x7f.0.0.1), and short-form (127.1)
    try:
        packed = socket.inet_aton(stripped)
        return ipaddress.IPv4Address(packed)
    except OSError:
        return None


def default_resolve_host_ips(hostname: str, port: int) -> List[IPAddress]:
    """Resolve hostname via OS DNS and return unique IPAddress objects."""
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except OSError:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    ips: List[IPAddress] = []
    seen: Set[str] = set()
    for info in infos:
        raw_ip = info[4][0].split("%")[0]
        if raw_ip not in seen:
            seen.add(raw_ip)
            ips.append(ipaddress.ip_address(raw_ip))
    return ips


def validate_outbound_url(
    url: str,
    *,
    allowed_ports: Optional[Set[int]] = None,
    resolve_fn: Optional[ResolveFn] = None,
    skip_dns: bool = False,
) -> ValidatedURL:
    """Validate URL syntax, port, host, and resolved IP addresses against SSRF."""
    if not url or not isinstance(url, str):
        raise UnsafeURLError("الرابط مطلوب.")

    raw = url.strip()
    if any(ch in raw for ch in ("\\", "\r", "\n", "\t", "\x00")):
        raise UnsafeURLError("الرابط يحتوي على محارف غير صالحة.")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise UnsafeURLError("يُسمح فقط بروابط http أو https.")

    if parsed.username is not None or parsed.password is not None or "@" in (parsed.netloc or ""):
        raise UnsafeURLError("يُمنع استخدام بيانات الدخول داخل الرابط.")

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise UnsafeURLError("الرابط لا يحتوي على اسم نطاق صالح.")

    if hostname in _FORBIDDEN_HOSTNAMES or any(hostname.endswith(sfx) for sfx in _FORBIDDEN_SUFFIXES):
        raise UnsafeURLError(f"النطاق '{hostname}' محظور لأسباب أمنية.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError("رقم المنفذ في الرابط غير صالح.") from exc

    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    permitted_ports = allowed_ports if allowed_ports is not None else settings.allowed_outbound_ports
    if effective_port not in permitted_ports:
        raise UnsafeURLError(f"المنفذ {effective_port} غير مسموح به للاتصال الخارجي.")

    # Check literal or obfuscated IP addresses before any DNS lookup
    literal_ip = _parse_obfuscated_ip(hostname)
    if literal_ip is not None:
        if _is_forbidden_ip(literal_ip):
            raise UnsafeURLError("الوصول إلى عناوين الشبكة الداخلية أو المحلية محظور.")
        return ValidatedURL(
            url=raw,
            hostname=hostname,
            port=effective_port,
            resolved_ips=(str(literal_ip),),
        )

    if skip_dns:
        return ValidatedURL(url=raw, hostname=hostname, port=effective_port, resolved_ips=())

    resolver = resolve_fn or default_resolve_host_ips
    try:
        resolved = resolver(hostname, effective_port)
    except OSError as exc:
        raise UnsafeURLError(f"تعذر حل اسم النطاق '{hostname}'.") from exc

    if not resolved:
        raise UnsafeURLError(f"تعذر العثور على عنوان IP صالح للنطاق '{hostname}'.")

    for ip in resolved:
        if _is_forbidden_ip(ip):
            raise UnsafeURLError("النطاق يشير إلى عنوان داخلي أو محجوز غير مسموح به.")

    return ValidatedURL(
        url=raw,
        hostname=hostname,
        port=effective_port,
        resolved_ips=tuple(str(ip) for ip in resolved),
    )


class _PinnedSyncBackend(httpcore.SyncBackend):
    """Connects strictly to the pre-validated IP while preserving TLS SNI."""

    def __init__(self, pinned_ips: dict[str, str], resolve_fn: Optional[ResolveFn] = None) -> None:
        self._pinned_ips = pinned_ips
        self._resolve_fn = resolve_fn

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.NetworkStream:
        key = host.lower().rstrip(".")
        target_ip = self._pinned_ips.get(key)
        if target_ip is None:
            validated = validate_outbound_url(
                f"https://{host}:{port}/",
                allowed_ports={port},
                resolve_fn=self._resolve_fn,
            )
            target_ip = validated.resolved_ips[0]
        return super().connect_tcp(
            target_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class _PinnedHTTPTransport(httpx.HTTPTransport):
    """HTTPTransport backed by a connection pool that pins validated IPs."""

    def __init__(self, pinned_ips: dict[str, str], resolve_fn: Optional[ResolveFn] = None) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=5.0,
            network_backend=_PinnedSyncBackend(pinned_ips, resolve_fn=resolve_fn),
        )


def _content_type_allowed(content_type: str, allowed_types: Sequence[str]) -> bool:
    if not allowed_types:
        return True
    mime = (content_type or "").split(";")[0].strip().lower()
    if not mime:
        return True
    return any(mime == allowed.lower() for allowed in allowed_types)


def _read_bounded_body(response: httpx.Response, max_bytes: int) -> str:
    content_length = response.headers.get("content-length")
    if content_length and content_length.strip().isdigit():
        if int(content_length.strip()) > max_bytes:
            raise UnsafeURLError("حجم الصفحة يتجاوز الحد الأقصى المسموح به.")

    chunks: List[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise UnsafeURLError("حجم الصفحة يتجاوز الحد الأقصى المسموح به.")
        chunks.append(chunk)

    encoding = response.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


@dataclass
class SafeFetchResult:
    final_url: str
    status_code: int
    text: str
    headers: httpx.Headers


def safe_request(
    method: str,
    url: str,
    *,
    client: Optional[httpx.Client] = None,
    resolve_fn: Optional[ResolveFn] = None,
    allowed_ports: Optional[Set[int]] = None,
    allowed_content_types: Optional[Sequence[str]] = _DEFAULT_HTML_TYPES,
    max_bytes: Optional[int] = None,
    max_redirects: Optional[int] = None,
    timeout: float = 15.0,
    headers: Optional[dict[str, str]] = None,
    json_body: Optional[dict] = None,
    hop_validator: Optional[Callable[[str], None]] = None,
) -> SafeFetchResult:
    """Safely execute an outbound HTTP request with SSRF validation on every hop."""
    byte_cap = max_bytes if max_bytes is not None else settings.MAX_FETCH_BYTES
    hop_cap = max_redirects if max_redirects is not None else settings.MAX_REDIRECT_HOPS
    req_headers = dict(_DEFAULT_CLIENT_HEADERS)
    if headers:
        req_headers.update(headers)

    is_mock_client = client is not None and isinstance(
        getattr(client, "_transport", None), httpx.MockTransport
    )
    skip_dns = is_mock_client and resolve_fn is None

    current_url = url.strip()
    pinned_ips: dict[str, str] = {}

    for _hop in range(hop_cap + 1):
        if hop_validator is not None:
            hop_validator(current_url)

        validated = validate_outbound_url(
            current_url,
            allowed_ports=allowed_ports,
            resolve_fn=resolve_fn,
            skip_dns=skip_dns,
        )
        if validated.resolved_ips:
            pinned_ips[validated.hostname] = validated.resolved_ips[0]

        own_client = client is None
        active_client = client
        if active_client is None:
            transport = _PinnedHTTPTransport(pinned_ips, resolve_fn=resolve_fn)
            active_client = httpx.Client(
                timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)),
                follow_redirects=False,
                headers=req_headers,
                transport=transport,
                trust_env=False,
            )

        try:
            stream_kwargs: dict = {"headers": req_headers}
            if json_body is not None:
                stream_kwargs["json"] = json_body
            with active_client.stream(
                method.upper(),
                validated.url,
                follow_redirects=False,
                **stream_kwargs,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeURLError("إعادة توجيه بدون وجهة صالحة.")
                    current_url = urljoin(validated.url, location.strip())
                    if response.status_code in {301, 302, 303} and method.upper() == "POST":
                        method = "GET"
                        json_body = None
                    continue

                if allowed_content_types is not None and response.status_code == 200:
                    ct = response.headers.get("content-type", "")
                    if not _content_type_allowed(ct, allowed_content_types):
                        raise UnsafeURLError(f"نوع المحتوى '{ct.split(';')[0].strip()}' غير مسموح به.")

                body_text = _read_bounded_body(response, byte_cap)
                return SafeFetchResult(
                    final_url=str(response.url) or validated.url,
                    status_code=response.status_code,
                    text=body_text,
                    headers=response.headers,
                )
        finally:
            if own_client:
                active_client.close()

    raise UnsafeURLError(f"تجاوز الرابط الحد الأقصى لإعادة التوجيه ({hop_cap}).")
