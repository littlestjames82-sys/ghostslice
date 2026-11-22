"""Positive: ssl.wrap_socket / ssl.match_hostname were removed in Python 3.12."""
import ssl


def wrap(sock, cert, host):
    wrapped = ssl.wrap_socket(sock)
    ok = ssl.match_hostname(cert, host)
    return wrapped, ok
