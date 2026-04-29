"""Helpers for local Ansys batch exports in the SCDevice tree."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from shutil import copy2

from kqcircuits.defaults import ANSYS_EXECUTABLE as KQC_ANSYS_EXECUTABLE
from kqcircuits.pya_resolver import pya
from kqcircuits.util.load_save_layout import save_layout


LOCAL_ANSYS_HELPER_DIR = Path(__file__).with_name("ansys_local")
SIMULATION_BATCH_FILENAME = "simulation_batch.json"
PYEPR_PARAMETER_FILENAME = "run_pyepr_t1_estimate.json"
ANSYS_EXECUTABLE_ENV = "SCDEVICE_ANSYS_EXECUTABLE"
PYEPR_PYTHON_ENV = "SCDEVICE_PYEPR_PYTHON"
ANSYS_EXECUTABLE_NAMES = ("ansysedt.exe", "ansysedtsv.exe")
PYEPR_REQUIRED_MODULES = ("pyEPR", "qutip", "pandas", "win32com", "pythoncom")
EIGENMODE_FIELD_SAVE_NEEDLE = '''            "IsEnabled:=",
            True,
            "BasisOrder:=",
            setup["basis_order"],'''
EIGENMODE_FIELD_SAVE_REPLACEMENT = '''            "IsEnabled:=",
            True,
            "SaveRadFieldsOnly:=",
            False,
            "SaveAnyFields:=",
            True,
            "BasisOrder:=",
            setup["basis_order"],'''
ANSYS_GDS_LAYER_START = 1


def _existing_file(path):
    path = Path(os.path.expandvars(str(path))).expanduser()
    return path if path.is_file() else None


def _iter_ansys_executable_candidates():
    """Yield local Ansys Electronics Desktop executables, including Student."""
    override = os.environ.get(ANSYS_EXECUTABLE_ENV) or os.environ.get("ANSYS_EXECUTABLE")
    if override:
        yield override

    yield KQC_ANSYS_EXECUTABLE

    program_roots = []
    for env_name in ("ProgramFiles", "ProgramW6432"):
        root = os.environ.get(env_name)
        if root:
            program_roots.append(Path(root))

    install_roots = []
    for root in program_roots:
        install_roots.extend([root / "AnsysEM", root / "ANSYS Inc", root / "ANSYS Student"])

    for install_root in install_roots:
        if not install_root.is_dir():
            continue
        version_dirs = sorted(
            (path for path in install_root.iterdir() if path.is_dir() and path.name.lower().startswith("v")),
            reverse=True,
        )
        for version_dir in version_dirs:
            for exe_dir in (version_dir / "Win64", version_dir / "AnsysEM" / "Win64", version_dir / "AnsysEM"):
                for executable_name in ANSYS_EXECUTABLE_NAMES:
                    yield exe_dir / executable_name


def resolve_ansys_executable():
    """Return the AEDT executable path used by generated batch files."""
    for candidate in _iter_ansys_executable_candidates():
        executable = _existing_file(candidate)
        if executable:
            return executable
    return Path(os.path.expandvars(str(KQC_ANSYS_EXECUTABLE)))


def resolve_pyepr_python():
    """Return the Python executable used for pyEPR post-processing."""
    override = os.environ.get(PYEPR_PYTHON_ENV)
    return Path(os.path.expandvars(override)).expanduser() if override else Path(sys.executable)


def warn_if_pyepr_python_missing_modules(python_executable: Path):
    """Log a warning if the selected pyEPR Python cannot import required modules."""
    if not python_executable.is_file():
        logging.warning("pyEPR Python executable does not exist: %s", python_executable)
        return

    check = (
        "import importlib.util, sys; "
        f"missing = [m for m in {PYEPR_REQUIRED_MODULES!r} if importlib.util.find_spec(m) is None]; "
        "print(','.join(missing)); "
        "sys.exit(1 if missing else 0)"
    )
    try:
        result = subprocess.run(
            [str(python_executable), "-c", check],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError as error:
        logging.warning("Unable to check pyEPR Python '%s': %s", python_executable, error)
        return

    missing = result.stdout.strip()
    if result.returncode != 0 and missing:
        logging.warning(
            "pyEPR post-processing Python '%s' is missing modules: %s. "
            "Install them there or set %s to another Python executable.",
            python_executable,
            missing,
            PYEPR_PYTHON_ENV,
        )


def get_pyepr_parameters():
    """Return pyEPR post-processing parameters for local eigenmode sweeps."""
    return {
        "substrate_loss_tangent": 5e-7,
        "dielectric_surfaces": {
            "layerMA": {
                "tan_delta_surf": 9.9e-3,
                "th": 4.8e-9,
                "eps_r": 8,
            },
            "layerMS": {
                "tan_delta_surf": 2.6e-3,
                "th": 0.3e-9,
                "eps_r": 11.4,
            },
            "layerSA": {
                "tan_delta_surf": 2.1e-3,
                "th": 2.4e-9,
                "eps_r": 4,
            },
        },
    }


def write_json_file(path: Path, data) -> Path:
    """Write a UTF-8 JSON file."""
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
    return path


def write_simulation_batch_manifest(path: Path, simulations) -> Path:
    """Save exported json filenames for a single-session batch import."""
    manifest_path = path / SIMULATION_BATCH_FILENAME
    json_filenames = [f"{simulation.name}.json" for simulation in simulations]
    return write_json_file(manifest_path, {"json_filenames": json_filenames})


def _simulation_json_paths(path: Path, simulation):
    exact_path = path / f"{simulation.name}.json"
    if exact_path.exists():
        return [exact_path]
    return [
        candidate
        for candidate in sorted(path.glob(f"{simulation.name}*.json"))
        if candidate.name not in {SIMULATION_BATCH_FILENAME, PYEPR_PARAMETER_FILENAME}
    ]


def simulations_request_pyepr(path: Path, simulations):
    """Return True if any exported simulation JSON asks for pyEPR post-processing."""
    for simulation in simulations:
        for json_path in _simulation_json_paths(path, simulation):
            with open(json_path, "r", encoding="utf-8-sig") as file:
                json_data = json.load(file)
            if "pyepr" in json_data.get("simulation_flags", []):
                return True
    return False


def rewrite_ansys_gds_layers(path: Path, simulations):
    """Rewrite Ansys GDS files using GDS-compatible layer numbers and update JSON metadata."""
    for simulation in simulations:
        json_paths = _simulation_json_paths(path, simulation)
        if not json_paths:
            logging.warning("Cannot rewrite Ansys GDS layers; missing JSON for simulation %s", simulation.name)
            continue

        for json_path in json_paths:
            with open(json_path, "r", encoding="utf-8-sig") as file:
                json_data = json.load(file)

            gds_file = json_data.get("gds_file")
            layers = json_data.get("layers", {})
            if not gds_file or not layers:
                continue

            gds_path = path / gds_file
            layer_map = {}
            next_layer = ANSYS_GDS_LAYER_START
            for layer_name, layer_data in layers.items():
                if "layer" not in layer_data:
                    continue
                if next_layer > 255:
                    raise ValueError("Ansys GDS export needs at most 255 simulation layers.")
                layer_map[layer_name] = (layer_data["layer"], next_layer)
                layer_data["layer"] = next_layer
                next_layer += 1

            gds_scaling = json_data.get("gds_scaling", min(1e3 * simulation.layout.dbu, 1.0))
            gds_layout = pya.Layout()
            gds_layout.dbu = simulation.layout.dbu / gds_scaling
            gds_cell = gds_layout.create_cell(simulation.name)
            gds_layers = []
            for layer_name, (source_layer, gds_layer) in layer_map.items():
                source_index = simulation.layout.layer(pya.LayerInfo(source_layer, 0, layer_name))
                region = pya.Region(simulation.cell.begin_shapes_rec(source_index))
                if region.is_empty():
                    source_index = simulation.layout.layer(pya.LayerInfo(source_layer, 0))
                    region = pya.Region(simulation.cell.begin_shapes_rec(source_index))
                if region.is_empty():
                    logging.warning("Skipping empty Ansys GDS layer %s for %s", layer_name, simulation.name)
                    continue
                target_info = pya.LayerInfo(gds_layer, 0, layer_name)
                gds_layers.append(target_info)
                gds_cell.shapes(gds_layout.layer(target_info)).insert(region)

            save_layout(gds_path, gds_layout, [gds_cell], gds_layers, no_empty_cells=True)
            write_json_file(json_path, json_data)


def copy_local_ansys_helpers(path: Path):
    """Copy local batch helper scripts into the export scripts folder."""
    scripts_path = path / "scripts"
    scripts_path.mkdir(exist_ok=True)
    for helper_name in ("import_simulation_batch.py", "run_pyepr_t1_estimate_batch.py"):
        copy2(LOCAL_ANSYS_HELPER_DIR / helper_name, scripts_path / helper_name)


def patch_eigenmode_field_saving(path: Path):
    """Ensure exported HFSS eigenmode setup saves fields needed by pyEPR."""
    script_path = path / "scripts" / "import_simulation_geometry.py"
    if not script_path.exists():
        logging.warning("Cannot patch eigenmode field saving; missing %s", script_path)
        return

    script_text = script_path.read_text(encoding="utf-8")
    eigenmode_section_start = script_text.find('elif ansys_tool == "eigenmode":')
    eigenmode_section_end = script_text.find("else:  # use ansys_project_template", eigenmode_section_start)
    if eigenmode_section_start < 0 or eigenmode_section_end < 0:
        logging.warning("Cannot patch eigenmode field saving; eigenmode setup block not found in %s", script_path)
        return

    eigenmode_section = script_text[eigenmode_section_start:eigenmode_section_end]
    if '"SaveAnyFields:="' in eigenmode_section:
        return
    if EIGENMODE_FIELD_SAVE_NEEDLE not in eigenmode_section:
        logging.warning("Cannot patch eigenmode field saving; setup anchor not found in %s", script_path)
        return

    patched_section = eigenmode_section.replace(
        EIGENMODE_FIELD_SAVE_NEEDLE,
        EIGENMODE_FIELD_SAVE_REPLACEMENT,
        1,
    )
    script_path.write_text(
        script_text[:eigenmode_section_start] + patched_section + script_text[eigenmode_section_end:],
        encoding="utf-8",
        newline="\n",
    )


def write_simulation_bat(path: Path, sim_tool: str, enable_pyepr=False):
    """Rewrite simulation.bat to run the local single-session batch flow."""
    bat_path = path / "simulation.bat"
    ansys_script = str(Path("scripts").joinpath("import_simulation_batch.py"))
    ansys_executable = resolve_ansys_executable()
    lines = [
        "@echo off",
        "cd /d %~dp0",
        r'powershell -Command "Get-Process | Where-Object {$_.MainWindowTitle -like \"Run Simulations*\"} | Select -ExpandProperty Id | Export-Clixml -path blocking_pids.xml"',
        "title Run Simulations",
        r'powershell -Command "$sim_pids = Import-Clixml -Path blocking_pids.xml; if ($sim_pids) { echo \"Waiting for $sim_pids\"; Wait-Process $sim_pids -ErrorAction SilentlyContinue }; Remove-Item blocking_pids.xml"',
        f"echo Batch import - {sim_tool}",
        f'"{ansys_executable}" -scriptargs "{SIMULATION_BATCH_FILENAME}" -RunScriptAndExit "{ansys_script}"',
    ]
    if sim_tool == "eigenmode" and enable_pyepr:
        pyepr_script = str(Path("scripts").joinpath("run_pyepr_t1_estimate_batch.py"))
        pyepr_python = resolve_pyepr_python()
        warn_if_pyepr_python_missing_modules(pyepr_python)
        module_check = (
            "import importlib.util, sys; "
            f"missing = [m for m in {PYEPR_REQUIRED_MODULES!r} if importlib.util.find_spec(m) is None]; "
            "print('Missing pyEPR dependencies: ' + ', '.join(missing)) if missing else None; "
            "sys.exit(1 if missing else 0)"
        )
        lines.extend(
            [
                "echo Post-process",
                f'set "{PYEPR_PYTHON_ENV}={pyepr_python}"',
                "set \"PYTHONIOENCODING=utf-8\"",
                f'"%{PYEPR_PYTHON_ENV}%" -c "{module_check}"',
                "if errorlevel 1 (",
                f"    echo Install pyEPR dependencies into %{PYEPR_PYTHON_ENV}% or set {PYEPR_PYTHON_ENV} to another Python.",
                "    exit /b 1",
                ")",
                f'"%{PYEPR_PYTHON_ENV}%" "{pyepr_script}" "{SIMULATION_BATCH_FILENAME}" "{PYEPR_PARAMETER_FILENAME}"',
            ]
        )

    with open(bat_path, "w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines) + "\n")


def configure_ansys_batch(path: Path, simulations, sim_tool: str):
    """Write local helper files and a custom batch runner for the export folder."""
    rewrite_ansys_gds_layers(path, simulations)
    write_simulation_batch_manifest(path, simulations)
    enable_pyepr = sim_tool == "eigenmode" and simulations_request_pyepr(path, simulations)
    if enable_pyepr:
        write_json_file(path / PYEPR_PARAMETER_FILENAME, get_pyepr_parameters())
    else:
        stale_pyepr_parameters = path / PYEPR_PARAMETER_FILENAME
        if stale_pyepr_parameters.exists():
            stale_pyepr_parameters.unlink()
    copy_local_ansys_helpers(path)
    if enable_pyepr:
        patch_eigenmode_field_saving(path)
    write_simulation_bat(path, sim_tool, enable_pyepr=enable_pyepr)
