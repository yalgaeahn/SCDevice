"""Local export path helpers for SCDevice simulations."""

import json
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


def make_simulation_bat_location_independent(export_path, file_prefix="simulation"):
    """Make KQ-generated batch files safe to launch by absolute path."""
    bat_path = Path(export_path) / f"{file_prefix}.bat"
    if not bat_path.exists():
        raise FileNotFoundError(f"Missing KQ-generated batch file: {bat_path}")

    text = bat_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if any(line.strip().lower() == "cd /d %~dp0" for line in lines[:3]):
        return bat_path

    insert_at = 1 if lines and lines[0].strip().lower() == "@echo off" else 0
    lines.insert(insert_at, "cd /d %~dp0")
    bat_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return bat_path


def add_kq_post_process_tool_metadata(export_path):
    """Add the top-level ``tool`` key expected by KQ post-process scripts."""
    for json_path in Path(export_path).glob("*.json"):
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        if "tool" in data or "ansys_tool" not in data:
            continue
        data["tool"] = data["ansys_tool"]
        json_path.write_text(json.dumps(data, indent=4), encoding="utf-8", newline="\n")
