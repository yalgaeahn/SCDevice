"""Local export path helpers for SCDevice simulations."""

from pathlib import Path
from shutil import rmtree


SCDEVICE_ROOT = Path(__file__).resolve().parents[2]
SCDEVICE_TMP_PATH = SCDEVICE_ROOT / "tmp"


def create_or_empty_scdevice_tmp_directory(dir_name):
    """Create or empty ``SCDevice/tmp/<dir_name>`` without using KQCircuits' TMP_PATH."""
    tmp_path = SCDEVICE_TMP_PATH.resolve()
    path = (tmp_path / dir_name).resolve()
    if not path.is_relative_to(tmp_path):
        raise ValueError(f"Refusing to create export path outside SCDevice/tmp: {path}")

    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir():
            rmtree(child)
        else:
            child.unlink()
    return path
