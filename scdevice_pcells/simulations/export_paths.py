"""Local export path helpers for SCDevice simulations."""

import json
from pathlib import Path
from shutil import rmtree

SCDEVICE_ROOT = Path(__file__).resolve().parents[2]
SCDEVICE_TMP_PATH = SCDEVICE_ROOT / "tmp"
SCDEVICE_VENV_PYTHON = SCDEVICE_ROOT / ".venv" / "Scripts" / "python.exe"
KQC_VENV_PYTHON = SCDEVICE_ROOT / "KQCircuits" / ".venv" / "Scripts" / "python.exe"
SCDEVICE_PYTHON_SITECUSTOMIZE = Path(__file__).resolve().with_name("python_sitecustomize")


def post_process_python_executable():
    """Return the preferred Python executable for generated post-process commands."""
    for candidate in (SCDEVICE_VENV_PYTHON, KQC_VENV_PYTHON):
        if candidate.exists():
            return candidate
    return None


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
    """Make KQ-generated batch files safe to launch by absolute path.

    KQCircuits writes post-process lines as ``python scripts/...``. On Windows
    that can resolve to a system Python instead of the project venv, which is
    fatal for pyEPR. Pin post-process Python calls to the project venv and add
    SCDevice's runtime compatibility patches via ``sitecustomize.py``.
    """
    bat_path = Path(export_path) / f"{file_prefix}.bat"
    if not bat_path.exists():
        raise FileNotFoundError(f"Missing KQ-generated batch file: {bat_path}")

    text = bat_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not any(line.strip().lower() == "cd /d %~dp0" for line in lines[:3]):
        insert_at = 1 if lines and lines[0].strip().lower() == "@echo off" else 0
        lines.insert(insert_at, "cd /d %~dp0")

    cd_index = next(
        (index for index, line in enumerate(lines) if line.strip().lower() == "cd /d %~dp0"),
        0,
    )
    env_lines = ["set PYTHONUTF8=1", "set PYTHONIOENCODING=utf-8"]
    if SCDEVICE_PYTHON_SITECUSTOMIZE.exists():
        env_lines.append(f'set "PYTHONPATH={SCDEVICE_PYTHON_SITECUSTOMIZE};%PYTHONPATH%"')
    for env_line in reversed(env_lines):
        if not any(line.strip().lower() == env_line.lower() for line in lines):
            lines.insert(cd_index + 1, env_line)

    post_process_python = post_process_python_executable()
    if post_process_python is not None:
        python_command = f'"{post_process_python}"'
        patched_lines = []
        for line in lines:
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            if stripped.lower().startswith("python "):
                patched_lines.append(f"{indent}{python_command} {stripped[7:]}")
            else:
                patched_lines.append(line)
        lines = patched_lines

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
