"""Make the kit's modules importable from the setup scripts."""
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
