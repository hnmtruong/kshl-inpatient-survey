#!/usr/bin/env python3
"""TCP relay exposing the survey HTTPS service on an additional internal port."""
from __future__ import annotations

import socket
import threading

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8766
TARGET = ("127.0.0.1", 8765)


def relay(source: socket.socket, destination: socket.socket) -> None:
    try:
        while data := source.recv(65536):
            destination.sendall(data)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client: socket.socket) -> None:
    try:
        upstream = socket.create_connection(TARGET, timeout=10)
        upstream.settimeout(None)
        client.settimeout(None)
        threading.Thread(target=relay, args=(client, upstream), daemon=True).start()
        relay(upstream, client)
    except OSError:
        pass
    finally:
        client.close()
        try:
            upstream.close()
        except UnboundLocalError:
            pass


with socket.create_server((LISTEN_HOST, LISTEN_PORT), reuse_port=False) as server:
    while True:
        client, _ = server.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()
