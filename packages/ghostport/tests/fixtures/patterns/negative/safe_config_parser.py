"""Look-alike negative: ConfigParser is the supported class."""
import configparser


def load(path):
    parser = configparser.ConfigParser()
    parser.read(path)
    return parser
