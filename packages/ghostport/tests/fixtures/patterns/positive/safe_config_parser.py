"""Positive: configparser.SafeConfigParser was removed in Python 3.12."""
import configparser


def load(path):
    parser = configparser.SafeConfigParser()
    parser.read(path)
    return parser
