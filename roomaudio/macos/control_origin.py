"""Same-origin CSRF guard for RoomAudio state-changing browser endpoints.

Fly Terminal can be reached through Oracle HTTPS, several Tailnet names, or
private direct LAN connections. Check the *actual* Host against Origin, then
restrict both to these controlled namespaces; never trust caller-supplied
X-Forwarded-Host as an alternative authority.
"""
import ipaddress
from urllib.parse import urlsplit

TAILNET_SUFFIX = ".tail1c55c5.ts.net"
PUBLIC_ORIGIN_HOSTS = {"129-158-49-130.sslip.io"}
LOCAL_ORIGIN_HOSTS = {"localhost", "kruspe-mac-mini.local"}
TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def permitted_origin(origin, request_host):
    """Accept browser writes only from this app on a trusted authority."""
    if not isinstance(origin, str) or not isinstance(request_host, str):
        return False
    if not origin or not request_host or len(origin) > 300 or len(request_host) > 255:
        return False
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if (not host or parsed.username is not None or parsed.password is not None or
            parsed.path or parsed.query or parsed.fragment or
            parsed.netloc.lower() != request_host.strip().lower()):
        return False
    host = host.lower()
    if parsed.scheme == "https":
        return host in PUBLIC_ORIGIN_HOSTS or (host.endswith(TAILNET_SUFFIX) and
               len(host) > len(TAILNET_SUFFIX))
    if parsed.scheme != "http" or port != 8766:
        return False
    if host in LOCAL_ORIGIN_HOSTS:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address in TAILSCALE_CGNAT
