"""Security helpers for ARC's unauthenticated local browser control planes.

ARC's browser UIs can execute agents, mutate task state, start local processes,
and integrate Git candidates. Until ARC has a real authenticated multi-user
boundary these surfaces are intentionally loopback-only.

The HTTP origin guard also protects localhost APIs from cross-site browser
requests. Non-browser clients may omit Origin; browsers that send an Origin
must identify a loopback host.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


_LOCAL_NAMES = {"localhost", "localhost.localdomain"}


def is_loopback_host(host: str) -> bool:
    """Return True only when *all* resolved addresses are loopback addresses."""
    value = (host or "").strip().lower()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if value in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(value, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {item[4][0] for item in infos if item[4]}
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(address).is_loopback for address in addresses)
    except ValueError:
        return False


def is_loopback_origin(origin: str | None) -> bool:
    """Validate a browser Origin value against ARC's local-only boundary."""
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return is_loopback_host(parsed.hostname)


def require_loopback_bind(host: str, surface: str) -> None:
    """Fail closed for any non-loopback bind until authenticated remote mode exists."""
    if is_loopback_host(host):
        return
    raise ValueError(
        f"{surface} is an unauthenticated local control plane and may only bind to loopback. "
        "Remote exposure is disabled until ARC provides an authenticated security boundary."
    )


class LocalOriginGuardMiddleware(BaseHTTPMiddleware):
    """Reject browser requests that originate outside the local machine."""

    async def dispatch(self, request: Request, call_next) -> Response:
        origin = request.headers.get("origin")
        if not is_loopback_origin(origin):
            return JSONResponse(
                status_code=403,
                content={"detail": "ARC local control plane rejected a non-loopback Origin"},
            )
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response
