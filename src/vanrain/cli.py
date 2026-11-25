"""Command-line interface. Thin wrapper over the Python API, no logic (milestone 5)."""

from __future__ import annotations

import sys

from vanrain import __version__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("-V", "--version"):
        print(f"vanrain {__version__}")
        return 0
    print("vanrain: no commands yet (index/context/find/stats arrive in milestone 5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
