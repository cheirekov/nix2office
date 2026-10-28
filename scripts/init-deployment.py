#!/usr/bin/env python3
"""Explicit initializer; --config accepts the same machine.toml as the menus."""
from nix2office.cli import main

if __name__ == "__main__":
    raise SystemExit(main(legacy=True))
