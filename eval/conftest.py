"""Lets `pytest eval/tests` import the harness package from eval/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
