"""Rebuild an agent's instructions file from its parts. Usage: python build-instructions.py <agent folder>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vfkit.config import load_config  # noqa: E402
from vfkit.instructions import build  # noqa: E402
from vfkit.runtime import load_profile  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    cfg = load_config(sys.argv[1])
    print(f"wrote {build(cfg.agent_dir, load_profile(cfg.runtime)['instructions_file'])}")
