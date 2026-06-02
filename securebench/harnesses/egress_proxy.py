"""Allowlisting HTTP proxy used by harness egress containers."""

from __future__ import annotations

import argparse
import ipaddress
import os
import select
import socket
import socketserver
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlsplit


ALLOWED_PORTS = {80, 443}


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
        self._tunnel(upstream)

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
        if url.scheme not in ("http", "https") or not url.hostname:
            self.send_error(400)
            return
        try:
            port = url.port or (443 if url.scheme == "https" else 80)
        except ValueError:
            self.send_error(400)
            return
        try:
            upstream = connect_allowed_destination(url.hostname, port, self.domains, timeout=self.timeout)
        except DestinationPolicyError:
            self.send_error(403)
            return
        except OSError:
            self.send_error(502)
            return
        with upstream:
            path = url.path or "/"
            if url.query:
                path += f"?{url.query}"
            upstream.sendall(f"{self.command} {path} {self.request_version}\r\n".encode("ascii"))
            for name, value in self.headers.items():
                if name.lower() in {"proxy-connection", "proxy-authorization"}:
                    continue
                upstream.sendall(f"{name}: {value}\r\n".encode("latin-1"))
            upstream.sendall(b"\r\n")
            content_length = self.headers.get("Content-Length")
            if content_length is not None:
                remaining = int(content_length)
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    upstream.sendall(chunk)
            self._copy_upstream_to_client(upstream)

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
