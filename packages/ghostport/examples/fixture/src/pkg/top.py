"""Fixture top module: depends on mid, has hits."""
import configparser
import ssl

from pkg import mid


def make():
    parser = configparser.SafeConfigParser()
    return ssl.wrap_socket(None), mid.stamp({})
