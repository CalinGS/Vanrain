"""Helpers."""

from typing import overload


def clean(text):
    return text.strip()


def shout(text):
    return text.upper()


@overload
def parse(value: int) -> int: ...


@overload
def parse(value: str) -> str: ...


def parse(value):
    """Parse a value."""
    return clean(value) if isinstance(value, str) else value
