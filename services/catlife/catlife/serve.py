"""Run an ASGI app on a dual-stack socket so it answers on IPv4 and IPv6 alike.

Railway's private network is IPv6 while public traffic can arrive over IPv4; uvicorn's
`--host ::` alone binds IPv6 only, so the socket is prepared here and handed over.
"""

from __future__ import annotations

import os
import socket

import uvicorn


def _dual_stack_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    return sock


def serve(app: object, default_port: int) -> None:
    port = int(os.environ.get("PORT", str(default_port)))
    try:
        sock = _dual_stack_socket(port)
    except OSError:
        uvicorn.run(app, host="0.0.0.0", port=port)
        return
    uvicorn.Server(uvicorn.Config(app)).run(sockets=[sock])


if __name__ == "__main__":
    serve("catlife.portal:app", 8000)
