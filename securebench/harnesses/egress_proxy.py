"""Allowlisting HTTP proxy used by harness egress containers."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import select
import socket
import socketserver
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from typing import Any, BinaryIO
from urllib.parse import urlsplit


ALLOWED_PORTS = {80, 443}
MAX_EGRESS_REQUEST_BYTES = 16 * 1024 * 1024
MAX_TLS_CLIENT_HELLO_BYTES = 64 * 1024
TLS_HANDSHAKE_CONTENT_TYPE = 22
TLS_CLIENT_HELLO_TYPE = 1
TLS_SERVER_NAME_EXTENSION = 0
TLS_HOST_NAME_TYPE = 0
HTTP_HEADER_NAME_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")


class DestinationPolicyError(Exception):
    """Requested egress destination violates the proxy policy."""


@dataclass(frozen=True)
class ResolvedAddress:
    """One validated numeric destination returned by DNS resolution."""

    family: int
    socktype: int
    proto: int
    sockaddr: tuple[Any, ...]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    allowed_domains = tuple(
        domain.strip().lower()
        for domain in os.environ.get("SECUREBENCH_ALLOWED_DOMAINS", "").split(",")
        if domain.strip()
    )
    if not allowed_domains:
        raise SystemExit("SECUREBENCH_ALLOWED_DOMAINS is required")

    class Handler(AllowlistingProxyHandler):
        domains = allowed_domains

    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.serve_forever()
    return 0


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class AllowlistingProxyHandler(BaseHTTPRequestHandler):
    domains: tuple[str, ...] = ()
    timeout = 20

    def do_CONNECT(self) -> None:
        destination = split_host_port(self.path, 443)
        if destination is None:
            self.send_error(400)
            return
        host, port = destination
        if port != 443:
            self.send_error(403)
            return
        try:
            upstream = connect_allowed_destination(host, port, self.domains, timeout=self.timeout)
        except DestinationPolicyError:
            self.send_error(403)
            return
        except OSError:
            self.send_error(502)
            return
        self.send_response(200, "Connection Established")
        self.end_headers()
        try:
            self.connection.settimeout(self.timeout)
            client_hello, server_name = read_tls_client_hello_from_socket(self.connection)
            if normalize_hostname(server_name) != normalize_hostname(host):
                raise DestinationPolicyError("TLS server name does not match CONNECT authority")
            upstream.sendall(client_hello)
            self._tunnel(upstream)
        except (DestinationPolicyError, OSError):
            upstream.close()

    def do_GET(self) -> None:
        self._proxy_absolute_request()

    def do_HEAD(self) -> None:
        self._proxy_absolute_request()

    def do_POST(self) -> None:
        self._proxy_absolute_request()

    def do_PUT(self) -> None:
        self._proxy_absolute_request()

    def do_PATCH(self) -> None:
        self._proxy_absolute_request()

    def do_DELETE(self) -> None:
        self._proxy_absolute_request()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _proxy_absolute_request(self) -> None:
        url = urlsplit(self.path)
        if url.scheme != "http" or not url.hostname or url.username is not None:
            self.send_error(400)
            return
        try:
            port = url.port or 80
        except ValueError:
            self.send_error(400)
            return
        if port != 80 or self.headers.get("Transfer-Encoding") is not None:
            self.send_error(400)
            return
        content_lengths = self.headers.get_all("Content-Length", [])
        if len(content_lengths) > 1:
            self.send_error(400)
            return
        content_length = content_lengths[0] if content_lengths else None
        remaining = 0
        if content_length is not None:
            try:
                remaining = int(content_length)
            except ValueError:
                self.send_error(400)
                return
            if remaining < 0:
                self.send_error(400)
                return
            if remaining > MAX_EGRESS_REQUEST_BYTES:
                self.send_error(413)
                return
        path = url.path or "/"
        if url.query:
            path += f"?{url.query}"
        try:
            request_line = f"{self.command} {path} {self.request_version}\r\n".encode("ascii")
        except UnicodeEncodeError:
            self.send_error(400)
            return
        forwarded_headers = self._forwarded_request_headers()
        if forwarded_headers is None:
            self.send_error(400)
            return
        try:
            upstream = connect_allowed_destination(
                url.hostname,
                port,
                self.domains,
                timeout=self.timeout,
            )
        except DestinationPolicyError:
            self.send_error(403)
            return
        except OSError:
            self.send_error(502)
            return
        with upstream:
            upstream.sendall(request_line)
            for header in forwarded_headers:
                upstream.sendall(header)
            upstream.sendall(f"Host: {http_host_header(url.hostname, port)}\r\n".encode("ascii"))
            if content_length is not None:
                upstream.sendall(f"Content-Length: {remaining}\r\n".encode("ascii"))
            upstream.sendall(b"Connection: close\r\n\r\n")
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    return
                remaining -= len(chunk)
                upstream.sendall(chunk)
            self._copy_upstream_to_client(upstream)

    def _forwarded_request_headers(self) -> tuple[bytes, ...] | None:
        connection_headers = {
            token.strip().lower()
            for value in self.headers.get_all("Connection", [])
            for token in value.split(",")
            if token.strip()
        }
        if any(not HTTP_HEADER_NAME_RE.fullmatch(name) for name in connection_headers):
            return None
        output = []
        for name, value in self.headers.items():
            if not _valid_http_header(name, value):
                return None
            lower = name.lower()
            if lower in connection_headers or lower in {
                "connection",
                "content-length",
                "host",
                "keep-alive",
                "proxy-connection",
                "proxy-authorization",
                "te",
                "trailer",
                "transfer-encoding",
                "upgrade",
            }:
                continue
            output.append(f"{name}: {value}\r\n".encode("latin-1"))
        return tuple(output)

    def _tunnel(self, upstream: socket.socket) -> None:
        with upstream:
            sockets = [self.connection, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], self.timeout)
                if not readable:
                    return
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        return
                    target = upstream if sock is self.connection else self.connection
                    target.sendall(data)

    def _copy_upstream_to_client(self, upstream: socket.socket) -> None:
        while True:
            data = upstream.recv(65536)
            if not data:
                return
            self.connection.sendall(data)


def split_host_port(authority: str, default_port: int) -> tuple[str, int] | None:
    if authority.startswith("["):
        end = authority.find("]")
        if end == -1:
            return None
        host = authority[1:end]
        rest = authority[end + 1 :]
        if rest.startswith(":"):
            return _host_port(host, rest[1:])
        return (host, default_port) if not rest else None
    if ":" not in authority:
        return authority, default_port
    host, port = authority.rsplit(":", 1)
    return _host_port(host, port)


def _host_port(host: str, port: str) -> tuple[str, int] | None:
    try:
        parsed = int(port)
    except ValueError:
        return None
    if parsed <= 0 or parsed > 65535:
        return None
    return host, parsed


def normalize_hostname(host: str) -> str:
    return host.lower().rstrip(".")


def http_host_header(host: str, port: int) -> str:
    normalized = normalize_hostname(host)
    if ":" in normalized:
        normalized = f"[{normalized}]"
    return normalized if port == 80 else f"{normalized}:{port}"


def _valid_http_header(name: str, value: str) -> bool:
    if not HTTP_HEADER_NAME_RE.fullmatch(name):
        return False
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return not any(
        (ord(character) < 0x20 and character != "\t") or ord(character) == 0x7F
        for character in value
    )


def read_tls_client_hello(
    reader: BinaryIO,
    *,
    max_bytes: int = MAX_TLS_CLIENT_HELLO_BYTES,
) -> tuple[bytes, str]:
    """Read one TLS ClientHello and return its wire bytes and cleartext SNI."""
    return _read_tls_client_hello(reader.read, max_bytes=max_bytes)


def read_tls_client_hello_from_socket(
    connection: socket.socket,
    *,
    max_bytes: int = MAX_TLS_CLIENT_HELLO_BYTES,
) -> tuple[bytes, str]:
    """Read a ClientHello without buffering bytes needed by the subsequent tunnel."""
    return _read_tls_client_hello(connection.recv, max_bytes=max_bytes)


def _read_tls_client_hello(
    read: Callable[[int], bytes],
    *,
    max_bytes: int,
) -> tuple[bytes, str]:
    wire = bytearray()
    handshake = bytearray()
    expected_handshake_bytes: int | None = None

    while expected_handshake_bytes is None or len(handshake) < expected_handshake_bytes:
        header = _read_exact(read, 5)
        if header[0] != TLS_HANDSHAKE_CONTENT_TYPE:
            raise DestinationPolicyError("TLS tunnel did not start with a handshake record")
        record_length = int.from_bytes(header[3:5], "big")
        if record_length == 0 or len(wire) + 5 + record_length > max_bytes:
            raise DestinationPolicyError("TLS ClientHello exceeds the proxy inspection limit")
        payload = _read_exact(read, record_length)
        wire.extend(header)
        wire.extend(payload)
        handshake.extend(payload)

        if expected_handshake_bytes is None and len(handshake) >= 4:
            if handshake[0] != TLS_CLIENT_HELLO_TYPE:
                raise DestinationPolicyError("TLS tunnel did not start with a ClientHello")
            expected_handshake_bytes = 4 + int.from_bytes(handshake[1:4], "big")
            if expected_handshake_bytes > max_bytes:
                raise DestinationPolicyError("TLS ClientHello exceeds the proxy inspection limit")

    if expected_handshake_bytes is None or len(handshake) != expected_handshake_bytes:
        raise DestinationPolicyError("TLS handshake record contains data after the ClientHello")
    server_name = client_hello_server_name(bytes(handshake[4:]))
    return bytes(wire), server_name


def _read_exact(read: Callable[[int], bytes], length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = read(length - len(data))
        if not chunk:
            raise DestinationPolicyError("TLS ClientHello ended prematurely")
        data.extend(chunk)
    return bytes(data)


def client_hello_server_name(client_hello: bytes) -> str:
    """Extract exactly one DNS host_name from a TLS ClientHello body."""
    offset = 34  # legacy_version (2) and random (32)
    offset = _skip_vector(client_hello, offset, length_bytes=1, field="session ID")
    offset = _skip_vector(client_hello, offset, length_bytes=2, field="cipher suites")
    offset = _skip_vector(client_hello, offset, length_bytes=1, field="compression methods")
    extensions, offset = _take_vector(
        client_hello,
        offset,
        length_bytes=2,
        field="extensions",
    )
    if offset != len(client_hello):
        raise DestinationPolicyError("malformed TLS ClientHello extensions")

    server_name: str | None = None
    extension_offset = 0
    while extension_offset < len(extensions):
        if extension_offset + 4 > len(extensions):
            raise DestinationPolicyError("malformed TLS extension header")
        extension_type = int.from_bytes(extensions[extension_offset : extension_offset + 2], "big")
        extension_length = int.from_bytes(
            extensions[extension_offset + 2 : extension_offset + 4],
            "big",
        )
        extension_offset += 4
        extension_end = extension_offset + extension_length
        if extension_end > len(extensions):
            raise DestinationPolicyError("malformed TLS extension body")
        extension = extensions[extension_offset:extension_end]
        extension_offset = extension_end
        if extension_type != TLS_SERVER_NAME_EXTENSION:
            continue
        if server_name is not None:
            raise DestinationPolicyError("TLS ClientHello contains duplicate SNI extensions")
        server_name = _server_name_from_extension(extension)

    if server_name is None:
        raise DestinationPolicyError("TLS ClientHello does not contain SNI")
    return server_name


def _server_name_from_extension(extension: bytes) -> str:
    names, offset = _take_vector(extension, 0, length_bytes=2, field="server names")
    if offset != len(extension):
        raise DestinationPolicyError("malformed TLS server-name extension")
    name_offset = 0
    host_name: str | None = None
    while name_offset < len(names):
        if name_offset + 3 > len(names):
            raise DestinationPolicyError("malformed TLS server-name entry")
        name_type = names[name_offset]
        name_length = int.from_bytes(names[name_offset + 1 : name_offset + 3], "big")
        name_offset += 3
        name_end = name_offset + name_length
        if name_end > len(names):
            raise DestinationPolicyError("malformed TLS server name")
        raw_name = names[name_offset:name_end]
        name_offset = name_end
        if name_type != TLS_HOST_NAME_TYPE:
            continue
        if host_name is not None or not raw_name or b"\x00" in raw_name:
            raise DestinationPolicyError("TLS ClientHello contains an invalid host_name")
        try:
            host_name = raw_name.decode("ascii")
        except UnicodeDecodeError as exc:
            raise DestinationPolicyError("TLS SNI host_name is not ASCII") from exc
    if host_name is None:
        raise DestinationPolicyError("TLS ClientHello does not contain a host_name")
    return host_name


def _skip_vector(data: bytes, offset: int, *, length_bytes: int, field: str) -> int:
    _, offset = _take_vector(data, offset, length_bytes=length_bytes, field=field)
    return offset


def _take_vector(
    data: bytes,
    offset: int,
    *,
    length_bytes: int,
    field: str,
) -> tuple[bytes, int]:
    length_end = offset + length_bytes
    if length_end > len(data):
        raise DestinationPolicyError(f"malformed TLS ClientHello {field}")
    length = int.from_bytes(data[offset:length_end], "big")
    value_end = length_end + length
    if value_end > len(data):
        raise DestinationPolicyError(f"malformed TLS ClientHello {field}")
    return data[length_end:value_end], value_end


def is_allowed_destination(host: str, port: int, allowed_domains: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return port in ALLOWED_PORTS and any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def connect_allowed_destination(
    host: str,
    port: int,
    allowed_domains: tuple[str, ...],
    *,
    timeout: float,
) -> socket.socket:
    """Connect to one validated numeric address for an allowlisted hostname."""
    if not is_allowed_destination(host, port, allowed_domains):
        raise DestinationPolicyError("destination hostname or port is not allowlisted")

    addresses = resolve_public_addresses(host, port)
    last_error: OSError | None = None
    for address in addresses:
        upstream = None
        try:
            upstream = socket.socket(address.family, address.socktype, address.proto)
            upstream.settimeout(timeout)
            upstream.connect(address.sockaddr)
        except OSError as exc:
            if upstream is not None:
                upstream.close()
            last_error = exc
            continue
        return upstream
    raise last_error or OSError("no resolved destination addresses were connectable")


def resolve_public_addresses(host: str, port: int) -> tuple[ResolvedAddress, ...]:
    """Resolve a hostname once and reject any DNS answer that is not public unicast."""
    records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not records:
        raise OSError("DNS lookup returned no addresses")

    addresses = []
    seen = set()
    for family, socktype, proto, _, sockaddr in records:
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise DestinationPolicyError("DNS lookup returned an unsupported address family")
        if socktype != socket.SOCK_STREAM:
            raise DestinationPolicyError("DNS lookup returned a non-stream socket")
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except (IndexError, TypeError, ValueError) as exc:
            raise DestinationPolicyError("DNS lookup returned a malformed address") from exc
        if (family == socket.AF_INET and address.version != 4) or (
            family == socket.AF_INET6 and address.version != 6
        ):
            raise DestinationPolicyError("DNS lookup returned an address with a mismatched family")
        if not is_public_unicast_address(address):
            raise DestinationPolicyError("DNS lookup returned a non-public address")
        key = (family, socktype, proto, sockaddr)
        if key not in seen:
            seen.add(key)
            addresses.append(ResolvedAddress(family, socktype, proto, sockaddr))
    if not addresses:
        raise OSError("DNS lookup returned no usable addresses")
    return tuple(addresses)


def is_public_unicast_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an IP address is a public unicast destination."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return is_public_unicast_address(address.ipv4_mapped)
    return address.is_global and not address.is_multicast and not getattr(address, "is_site_local", False)


if __name__ == "__main__":
    raise SystemExit(main())
