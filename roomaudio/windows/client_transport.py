"""Direct RoomAudio requests with explicitly configured alternate server URLs."""
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener


class ClientTransport:
    def __init__(self, config):
        candidates = [config["server"], *config.get("server_fallbacks", [])]
        self.servers = []
        for value in candidates:
            value = value.rstrip("/")
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Invalid RoomAudio endpoint")
            if value not in self.servers:
                self.servers.append(value)
        self.current = self.servers[0]
        self.http = build_opener(ProxyHandler({}))

    def open(self, path, *, headers=None, data=None, method=None, timeout=6):
        candidates = [self.current, *[s for s in self.servers if s != self.current]]
        for index, server in enumerate(candidates):
            request = Request(server + path, headers=headers or {}, data=data, method=method)
            try:
                response = self.http.open(request, timeout=timeout)
                self.current = server
                return response
            except HTTPError:
                # Authentication/protocol failures must not be retried on other hosts.
                raise
            except (URLError, OSError):
                if index == len(candidates) - 1:
                    raise
