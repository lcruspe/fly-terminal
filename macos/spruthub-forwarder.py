#!/usr/bin/env python3
import os
import selectors
import socket
import socketserver
import sys

LISTEN_HOST = os.environ.get("FLY_SPRUTHUB_FORWARD_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("FLY_SPRUTHUB_FORWARD_PORT", "7693"))
TARGET_HOST = os.environ.get("FLY_SPRUTHUB_TARGET_HOST", "192.168.1.100")
TARGET_PORT = int(os.environ.get("FLY_SPRUTHUB_TARGET_PORT", "80"))
CONNECT_TIMEOUT = float(os.environ.get("FLY_SPRUTHUB_CONNECT_TIMEOUT", "5"))
BUFFER_SIZE = 65536


class ForwardHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            upstream = socket.create_connection(
                (TARGET_HOST, TARGET_PORT), timeout=CONNECT_TIMEOUT
            )
        except OSError as exc:
            print(f"Sprut.Hub connect failed: {exc}", file=sys.stderr, flush=True)
            return

        self.request.settimeout(None)
        upstream.settimeout(None)
        selector = selectors.DefaultSelector()
        selector.register(self.request, selectors.EVENT_READ, upstream)
        selector.register(upstream, selectors.EVENT_READ, self.request)
        readable = {self.request, upstream}

        try:
            while readable:
                for key, _ in selector.select():
                    source = key.fileobj
                    destination = key.data
                    try:
                        data = source.recv(BUFFER_SIZE)
                    except OSError:
                        data = b""
                    if data:
                        try:
                            destination.sendall(data)
                        except OSError:
                            return
                        continue

                    try:
                        selector.unregister(source)
                    except Exception:
                        pass
                    readable.discard(source)
                    try:
                        destination.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
        finally:
            selector.close()
            upstream.close()


class ForwardServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(
        f"Sprut.Hub forwarder: {LISTEN_HOST}:{LISTEN_PORT} -> "
        f"{TARGET_HOST}:{TARGET_PORT}",
        flush=True,
    )
    with ForwardServer((LISTEN_HOST, LISTEN_PORT), ForwardHandler) as server:
        server.serve_forever(poll_interval=0.5)
