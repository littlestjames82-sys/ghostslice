"""Look-alike negative: SSLContext.wrap_socket is the supported API."""
import ssl


def wrap(sock, host):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return context.wrap_socket(sock, server_hostname=host)
