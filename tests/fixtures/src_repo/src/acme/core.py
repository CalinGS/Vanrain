"""Core logic."""

from acme.helpers import clean, parse

from .helpers import shout


def run(text):
    """Clean, parse and shout."""
    return shout(parse(clean(text)))
