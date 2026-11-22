import os

import numpy
import requests
from PIL import Image

from helper import greet


def main():
    print(greet(os.environ.get("USER", "world")))
    return requests, Image, numpy
