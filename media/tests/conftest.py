"""The media tools are scripts in media/tools (they import each other as `common`, `review`…): put them on the path."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
