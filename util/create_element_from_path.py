"""Compatibility wrapper for running KQCircuits' create_element_from_path from SCDevice."""

from pathlib import Path
import runpy


TARGET_SCRIPT = Path(__file__).resolve().parents[1] / "KQCircuits" / "util" / "create_element_from_path.py"

if not TARGET_SCRIPT.is_file():
    raise FileNotFoundError(f"Expected KQCircuits helper script at '{TARGET_SCRIPT}'")

# Preserve variables injected by KLayout, such as ``element_path``.
runpy.run_path(str(TARGET_SCRIPT), init_globals=globals())
