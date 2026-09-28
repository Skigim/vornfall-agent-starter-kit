"""Store a Vornfall API key without it ever appearing on screen or in a transcript.

Usage: python setup/store_key.py VAR   (then paste the key and press Enter; it is not echoed)"""
import getpass
import sys

import _kit  # noqa: F401

from vfkit.keys import store_key

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    value = getpass.getpass("Key (not shown): ").strip() if sys.stdin.isatty() else sys.stdin.readline().strip()
    try:
        print(f"stored in {sys.argv[1]} ({store_key(sys.argv[1], value)})")
    except ValueError as e:
        sys.exit(f"not stored: {e}")
