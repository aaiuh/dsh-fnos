#!/usr/bin/env python3
"""dsh-fnos gateway shim.

dsh's own web server refuses wildcard binds, announces itself with an ephemeral
`?token=` URL, and scopes its cookie to `/`. None of that can be pointed at a
gateway path or an fnOS socket on its own, so this shim sits in front of it.

Two listeners, one upstream:

  * a Unix socket (app.sock) the fnOS unified gateway forwards `/app/<app>/*` to;
  * a loopback TCP port a reverse proxy uses for the public entry.

Each listener owns its own path prefix. The shim strips it, rewrites the
authority so dsh's browser-trust fence accepts the request, and — when the
browser arrives without a session cookie — exchanges the startup token for one
internally so the token never appears in the address bar.

Stdlib only: the fpk needs no Python dependencies.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from typing import Iterable

UP_HOST = os.environ.get("DSH_HOST") or "127.0.0.1"
UP_PORT = int(os.environ.get("DSH_PORT") or "3080")
TOKEN_FILE = os.environ.get("DSH_TOKEN_FILE") or ""
NO_BUFFER = os.environ.get("DSH_NO_BUFFER") == "1"
AUTH_COOKIE_PREFIX = "dsh-auth-"
LOG_PATH = os.environ.get("DSH_SHIM_LOG") or ""

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}

_log_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [shim] {msg}\n"
    if LOG_PATH:
        try:
            with _log_lock, open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line)
            return
        except OSError:
            pass
    sys.stderr.write(line)
    sys.stderr.flush()


def read_token() -> str:
    """dsh prints a fresh token per start, so read it at use time."""
    if not TOKEN_FILE:
        return ""
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def has_session_cookie(cookie_headers: Iterable[str]) -> bool:
    for raw in cookie_headers:
        for part in raw.split(";"):
            if part.split("=", 1)[0].strip().startswith(AUTH_COOKIE_PREFIX):
                return True
    return False


def recv_until(sock: socket.socket, sep: bytes, limit: int = 1 << 20) -> bytes:
    buf = b""
    while sep not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
        if len(buf) > limit:
            break
    return buf


def parse_head(raw: bytes) -> tuple[str, list[tuple[str, str]], bytes]:
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    start = lines[0].decode("latin-1")
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.decode("latin-1").partition(":")
        headers.append((name.strip(), value.strip()))
    return start, headers, rest


def header_get(headers: list[tuple[str, str]], name: str) -> str:
    low = name.lower()
    for k, v in headers:
        if k.lower() == low:
            return v
    return ""


def strip_prefix(target: str, prefix: str) -> str:
    if prefix and target.startswith(prefix):
        rest = target[len(prefix):]
        return rest or "/"
    return target if target.startswith("/") else "/" + target


def rewrite_authority(k: str, v: str) -> str | None:
    """Return a replacement header value, or None to drop the header."""
    low = k.lower()
    if low == "host":
        return f"{UP_HOST}:{UP_PORT}"
    if low == "origin":
        return f"http://{UP_HOST}:{UP_PORT}"
    if low == "referer":
        _, _, tail = v.partition("://")
        _, _, path = tail.partition("/")
        return f"http://{UP_HOST}:{UP_PORT}/{path}"
    return None


def build_head(start: str, headers: list[tuple[str, str]], prefix: str,
               keep_upgrade: bool) -> bytes:
    method, _, rest = start.partition(" ")
    target, _, version = rest.partition(" ")
    out = [f"{method} {strip_prefix(target, prefix)} {version or 'HTTP/1.1'}"]
    for k, v in headers:
        low = k.lower()
        repl = rewrite_authority(k, v)
        if repl is not None:
            out.append(f"{k}: {repl}")
            continue
        if low == "host":
            continue
        if low == "connection" and keep_upgrade:
            out.append("Connection: Upgrade")
            continue
        if not keep_upgrade and low in HOP_BY_HOP:
            continue
        out.append(f"{k}: {v}")
    if not keep_upgrade:
        out.append("Connection: close")
    return ("\r\n".join(out) + "\r\n\r\n").encode("latin-1")


def mint_cookie() -> str | None:
    """Exchange the startup token for a session cookie, internally."""
    token = read_token()
    if not token:
        log("no startup token on disk; cannot mint a session cookie")
        return None
    try:
        up = socket.create_connection((UP_HOST, UP_PORT), timeout=10)
    except OSError as exc:
        log(f"token exchange connect failed: {exc}")
        return None
    try:
        up.sendall((
            f"GET /?token={token} HTTP/1.1\r\n"
            f"Host: {UP_HOST}:{UP_PORT}\r\n"
            "Connection: close\r\nAccept: */*\r\n\r\n"
        ).encode("latin-1"))
        raw = recv_until(up, b"\r\n\r\n")
    finally:
        up.close()
    if not raw:
        return None
    _, headers, _ = parse_head(raw)
    cookie = header_get(headers, "set-cookie")
    if not cookie or AUTH_COOKIE_PREFIX not in cookie:
        log("token exchange returned no session cookie")
        return None
    return cookie


def relay(up: socket.socket, client: socket.socket) -> None:
    while True:
        try:
            data = up.recv(65536)
        except OSError:
            break
        if not data:
            break
        try:
            client.sendall(data)
        except OSError:
            break


def pipe_client_to_upstream(client: socket.socket, up: socket.socket) -> None:
    try:
        while True:
            data = client.recv(65536)
            if not data:
                break
            up.sendall(data)
    except OSError:
        pass
    finally:
        try:
            up.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def tunnel_websocket(client: socket.socket, start: str,
                     headers: list[tuple[str, str]], body_rest: bytes,
                     prefix: str) -> None:
    try:
        up = socket.create_connection((UP_HOST, UP_PORT), timeout=30)
    except OSError as exc:
        log(f"ws connect failed: {exc}")
        client.close()
        return
    up.sendall(build_head(start, headers, prefix, keep_upgrade=True))
    if body_rest:
        up.sendall(body_rest)
    threading.Thread(target=pipe_client_to_upstream, args=(client, up), daemon=True).start()
    try:
        while True:
            data = up.recv(65536)
            if not data:
                break
            client.sendall(data)
    except OSError:
        pass
    finally:
        for s in (up, client):
            try:
                s.close()
            except OSError:
                pass


def handle(client: socket.socket, prefix: str) -> None:
    try:
        client.settimeout(300)
        raw = recv_until(client, b"\r\n\r\n")
        if not raw:
            client.close()
            return
        start, headers, body_rest = parse_head(raw)

        if header_get(headers, "upgrade").lower() == "websocket":
            tunnel_websocket(client, start, headers, body_rest, prefix)
            return

        cookies = [v for k, v in headers if k.lower() == "cookie"]
        if not has_session_cookie(cookies):
            cookie = mint_cookie()
            if cookie:
                target = start.partition(" ")[2].partition(" ")[0].split("?", 1)[0]
                client.sendall((
                    "HTTP/1.1 303 See Other\r\n"
                    f"Location: {target}\r\n"
                    f"Set-Cookie: {cookie}\r\n"
                    "Cache-Control: no-store\r\nContent-Length: 0\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("latin-1"))
                client.close()
                return

        up = socket.create_connection((UP_HOST, UP_PORT), timeout=30)
        up.sendall(build_head(start, headers, prefix, keep_upgrade=False))
        if body_rest:
            up.sendall(body_rest)

        length = header_get(headers, "content-length")
        if length.isdigit() and int(length) > len(body_rest):
            remaining = int(length) - len(body_rest)
            while remaining > 0:
                chunk = client.recv(min(65536, remaining))
                if not chunk:
                    break
                up.sendall(chunk)
                remaining -= len(chunk)

        first = recv_until(up, b"\r\n\r\n")
        if NO_BUFFER and b"\r\n\r\n" in first:
            # Append rather than rebuild: stripping hop-by-hop headers here
            # would drop Transfer-Encoding and leave a chunked body the browser
            # cannot parse — the page then hangs on "loading".
            cut = first.index(b"\r\n\r\n")
            first = first[:cut] + b"\r\nX-Accel-Buffering: no" + first[cut:]
        client.sendall(first)
        relay(up, client)
        up.close()
    except Exception as exc:  # noqa: BLE001 - one bad request must not kill the shim
        log(f"request failed: {type(exc).__name__}: {exc}")
    finally:
        try:
            client.close()
        except OSError:
            pass


def serve(listener: socket.socket, prefix: str) -> None:
    while True:
        try:
            conn, _ = listener.accept()
        except OSError:
            continue
        threading.Thread(target=handle, args=(conn, prefix), daemon=True).start()


def listen_unix(path: str) -> socket.socket:
    if os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    try:
        os.chmod(path, 0o777)
    except OSError:
        pass
    srv.listen(128)
    return srv


def listen_tcp(spec: str) -> socket.socket:
    host, _, port = spec.rpartition(":")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host or "127.0.0.1", int(port)))
    srv.listen(128)
    return srv


def main() -> int:
    started = 0
    sock_path = os.environ.get("DSH_GATEWAY_SOCK") or ""
    sock_prefix = (os.environ.get("DSH_GATEWAY_PREFIX") or "").rstrip("/")
    tcp_spec = os.environ.get("DSH_PUBLIC_TCP") or ""
    tcp_prefix = (os.environ.get("DSH_PUBLIC_PREFIX") or "").rstrip("/")

    log(f"start upstream={UP_HOST}:{UP_PORT} token_file={TOKEN_FILE}")

    if sock_path:
        srv = listen_unix(sock_path)
        log(f"listening unix:{sock_path} prefix={sock_prefix!r}")
        threading.Thread(target=serve, args=(srv, sock_prefix), daemon=True).start()
        started += 1
    if tcp_spec:
        srv = listen_tcp(tcp_spec)
        log(f"listening tcp:{tcp_spec} prefix={tcp_prefix!r}")
        threading.Thread(target=serve, args=(srv, tcp_prefix), daemon=True).start()
        started += 1
    if not started:
        log("nothing to listen on (set DSH_GATEWAY_SOCK and/or DSH_PUBLIC_TCP)")
        return 2

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
