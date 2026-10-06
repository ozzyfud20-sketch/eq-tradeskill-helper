"""Entry point: run with `python main.py` from this folder's parent, or `python -m eq_helper.main`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from eq_helper.gui import run

if __name__ == "__main__":
    run()
