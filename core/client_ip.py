from ipaddress import ip_address, ip_network

from django.conf import settings


def get_client_ip(request):
    """
    Return the client's IP address.

    X-Forwarded-For is trusted only when the immediate connection
    comes from a configured trusted proxy.
    """
    if request is None:
        return None

    remote_addr = request.META.get("REMOTE_ADDR")

    if not remote_addr:
        return None

    try:
        remote_ip = ip_address(remote_addr)
    except ValueError:
        return None

    trusted_proxies = getattr(settings, "TRUSTED_PROXY_IPS", ())

    is_trusted_proxy = any(remote_ip in ip_network(proxy, strict=False) for proxy in trusted_proxies)

    if not is_trusted_proxy:
        return str(remote_ip)

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "").strip()

    try:
        return str(ip_address(forwarded_for))
    except ValueError:
        return str(remote_ip)