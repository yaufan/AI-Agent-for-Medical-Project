"""The demo UI uses the shared assistant backend (packages/tools/agenttools/assistant.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/tools"))

from agenttools.assistant import *  # noqa: E402,F401,F403
from agenttools.assistant import agent  # noqa: E402,F401  (tests patch backend.agent)
