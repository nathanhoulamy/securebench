import io
import ipaddress
import socket
import ssl
from email.message import Message
from types import SimpleNamespace

import pytest

from securebench.harnesses import egress_proxy
from securebench.harnesses.egress_proxy import (
    AllowlistingProxyHandler,
    DestinationPolicyError,
    connect_allowed_destination,
    http_host_header,
    is_public_unicast_address,
    read_tls_client_hello,
    resolve_public_addresses,
)


PUBLIC_IPV4 = "8.8.8.8"
PUBLIC_IPV6 = "2606:4700:4700::1111"


def tls_client_hello(server_name: str | None) -> bytes:
    incoming = ssl.MemoryBIO()
    outgoing = ssl.MemoryBIO()
    context = ssl.create_default_context()
    connection = context.wrap_bio(
        incoming,
        outgoing,
        server_side=False,
        server_hostname=server_name,
    )
    with pytest.raises(ssl.SSLWantReadError):
        connection.do_handshake()
    return outgoing.read()


class ProxySocket:
    def __init__(self):
        self.sent = bytearray()
        self.closed = False
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, size):
        return b""

    def close(self):
        self.closed = True


def dns_record(address, *, family=socket.AF_INET, proto=socket.IPPROTO_TCP):
    sockaddr = (address, 443) if family == socket.AF_INET else (address, 443, 0, 0)
    return family, socket.SOCK_STREAM, proto, "", sockaddr


@pytest.mark.parametrize(
    "address",
    [
        PUBLIC_IPV4,
        PUBLIC_IPV6,
        "::ffff:8.8.8.8",
    ],
)
def test_public_unicast_address_accepts_public_destinations(address):
    assert is_public_unicast_address(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "192.0.2.1",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::",
        "ff02::1",
        "fec0::1",
        "::ffff:127.0.0.1",
    ],
)
def test_public_unicast_address_rejects_unsafe_destinations(address):
    assert is_public_unicast_address(ipaddress.ip_address(address)) is False


def test_resolve_public_addresses_accepts_public_ipv4_and_ipv6(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [
            dns_record(PUBLIC_IPV4),
            dns_record(PUBLIC_IPV6, family=socket.AF_INET6),
        ],
    )

    addresses = resolve_public_addresses("example.com", 443)

    assert [address.sockaddr for address in addresses] == [
        (PUBLIC_IPV4, 443),
        (PUBLIC_IPV6, 443, 0, 0),
    ]


@pytest.mark.parametrize(
    "records",
    [
        [dns_record("127.0.0.1")],
        [dns_record("10.0.0.1")],
        [dns_record("169.254.169.254")],
        [dns_record(PUBLIC_IPV4), dns_record("127.0.0.1")],
        [(socket.AF_UNIX, socket.SOCK_STREAM, 0, "", ("/tmp/socket",))],
        [(socket.AF_INET, socket.SOCK_DGRAM, 0, "", (PUBLIC_IPV4, 443))],
        [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("not-an-ip", 443))],
        [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (PUBLIC_IPV6, 443))],
        [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (PUBLIC_IPV4, 443, 0, 0))],
    ],
)
def test_resolve_public_addresses_rejects_unsafe_or_malformed_answers(monkeypatch, records):
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: records)

    with pytest.raises(DestinationPolicyError):
        resolve_public_addresses("example.com", 443)


def test_resolve_public_addresses_rejects_empty_lookup(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [])

    with pytest.raises(OSError, match="no addresses"):
        resolve_public_addresses("example.com", 443)


def test_resolve_public_addresses_propagates_dns_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("lookup failed")

    monkeypatch.setattr("socket.getaddrinfo", fail)

    with pytest.raises(socket.gaierror, match="lookup failed"):
        resolve_public_addresses("example.com", 443)


def test_connect_allowed_destination_resolves_once_and_connects_to_numeric_sockaddr(monkeypatch):
    lookups = []
    sockets = []

    class FakeSocket:
        def __init__(self, family, socktype, proto):
            self.family = family
            self.socktype = socktype
            self.proto = proto
            self.timeout = None
            self.sockaddr = None
            sockets.append(self)

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, sockaddr):
            self.sockaddr = sockaddr

        def close(self):
            pass

    def fake_getaddrinfo(*args, **kwargs):
        lookups.append((args, kwargs))
        return [dns_record(PUBLIC_IPV4)]

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("socket.socket", FakeSocket)

    upstream = connect_allowed_destination("example.com", 443, ("example.com",), timeout=7)

    assert upstream is sockets[0]
    assert len(lookups) == 1
    assert sockets[0].timeout == 7
    assert sockets[0].sockaddr == (PUBLIC_IPV4, 443)


def test_connect_allowed_destination_falls_back_across_safe_addresses(monkeypatch):
    sockets = []

    class FakeSocket:
        def __init__(self, family, socktype, proto):
            self.sockaddr = None
            self.closed = False
            sockets.append(self)

        def settimeout(self, timeout):
            pass

        def connect(self, sockaddr):
            self.sockaddr = sockaddr
            if len(sockets) == 1:
                raise OSError("first address unavailable")

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [
            dns_record("8.8.4.4"),
            dns_record(PUBLIC_IPV4),
        ],
    )
    monkeypatch.setattr("socket.socket", FakeSocket)

    upstream = connect_allowed_destination("example.com", 443, ("example.com",), timeout=7)

    assert upstream is sockets[1]
    assert sockets[0].closed is True
    assert [item.sockaddr for item in sockets] == [("8.8.4.4", 443), (PUBLIC_IPV4, 443)]


def test_connect_allowed_destination_falls_back_when_socket_creation_fails(monkeypatch):
    calls = []

    class FakeSocket:
        def __init__(self, family, socktype, proto):
            calls.append((family, socktype, proto))
            if len(calls) == 1:
                raise OSError("address family unavailable")

        def settimeout(self, timeout):
            pass

        def connect(self, sockaddr):
            self.sockaddr = sockaddr

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [
            dns_record(PUBLIC_IPV6, family=socket.AF_INET6),
            dns_record(PUBLIC_IPV4),
        ],
    )
    monkeypatch.setattr("socket.socket", FakeSocket)

    upstream = connect_allowed_destination("example.com", 443, ("example.com",), timeout=7)

    assert upstream.sockaddr == (PUBLIC_IPV4, 443)
    assert calls == [
        (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP),
    ]


def test_connect_allowed_destination_rejects_hostname_before_dns(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: pytest.fail("DNS should not run"))

    with pytest.raises(DestinationPolicyError):
        connect_allowed_destination("blocked.example", 443, ("example.com",), timeout=7)


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (DestinationPolicyError("blocked"), 403),
        (OSError("lookup failed"), 502),
    ],
)
def test_connect_handler_maps_policy_and_resolution_failures(monkeypatch, error, status):
    monkeypatch.setattr(
        "securebench.harnesses.egress_proxy.connect_allowed_destination",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )
    handler = object.__new__(AllowlistingProxyHandler)
    handler.path = "example.com:443"
    handler.domains = ("example.com",)
    errors = []
    handler.send_error = lambda value: errors.append(value)

    handler.do_CONNECT()

    assert errors == [status]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (DestinationPolicyError("blocked"), 403),
        (OSError("lookup failed"), 502),
    ],
)
def test_http_handler_maps_policy_and_resolution_failures(monkeypatch, error, status):
    monkeypatch.setattr(
        "securebench.harnesses.egress_proxy.connect_allowed_destination",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )
    handler = object.__new__(AllowlistingProxyHandler)
    handler.path = "http://example.com/resource"
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.headers = Message()
    handler.domains = ("example.com",)
    errors = []
    handler.send_error = lambda value: errors.append(value)

    handler._proxy_absolute_request()

    assert errors == [status]


def test_proxy_extracts_sni_from_tls_client_hello():
    wire = tls_client_hello("Example.COM")

    consumed, server_name = read_tls_client_hello(io.BytesIO(wire))

    assert consumed == wire
    assert server_name == "Example.COM"


def test_proxy_rejects_tls_client_hello_without_sni():
    with pytest.raises(DestinationPolicyError, match="SNI"):
        read_tls_client_hello(io.BytesIO(tls_client_hello(None)))


def test_proxy_rejects_connect_sni_that_differs_from_authority(monkeypatch):
    upstream = ProxySocket()
    monkeypatch.setattr(
        egress_proxy,
        "connect_allowed_destination",
        lambda *args, **kwargs: upstream,
    )
    handler = object.__new__(AllowlistingProxyHandler)
    handler.path = "example.com:443"
    handler.domains = ("example.com",)
    handler.rfile = io.BytesIO(tls_client_hello("other.example.com"))
    handler.connection = ProxySocket()
    handler.send_response = lambda *args, **kwargs: None
    handler.end_headers = lambda: None

    handler.do_CONNECT()

    assert upstream.closed is True
    assert upstream.sent == b""


def test_http_handler_forces_url_host_and_connection_close(monkeypatch):
    upstream = ProxySocket()
    connected = []

    def connect(host, port, domains, *, timeout):
        connected.append((host, port, domains, timeout))
        return upstream

    monkeypatch.setattr("securebench.harnesses.egress_proxy.connect_allowed_destination", connect)
    request_headers = Message()
    request_headers["Host"] = "attacker.example"
    request_headers["Proxy-Connection"] = "keep-alive"
    handler = object.__new__(AllowlistingProxyHandler)
    handler.path = "http://example.com/resource?query=yes"
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.headers = request_headers
    handler.rfile = io.BytesIO()
    handler.connection = SimpleNamespace(sendall=lambda content: None)
    handler.domains = ("example.com",)
    handler.timeout = 9

    handler._proxy_absolute_request()

    assert connected == [("example.com", 80, ("example.com",), 9)]
    forwarded = upstream.sent.decode("latin-1")
    assert forwarded.startswith("GET /resource?query=yes HTTP/1.1\r\n")
    assert "Host: example.com\r\n" in forwarded
    assert "Host: attacker.example" not in forwarded
    assert "Connection: close\r\n" in forwarded
    assert http_host_header("example.com", 80) == "example.com"
