"""Fixture leaf module with removed stdlib imports."""
import imp
from distutils import core


def load(name):
    return imp.load_source(name, name + ".py")
