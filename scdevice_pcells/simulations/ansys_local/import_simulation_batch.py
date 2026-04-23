# This is a Python 2.7 script that should be run in HFSS in order to import and run a batch of simulations.
import json
import os
import platform
import sys

import ScriptEnv


def write_simulation_machine_versions_file(oDesktop):
    """Write a SIMULATION_MACHINE_VERSIONS file in the current working directory."""
    versions = {}
    versions["platform"] = platform.platform()
    versions["python"] = sys.version_info
    versions["Ansys ElectronicsDesktop"] = oDesktop.GetVersion()

    with open("SIMULATION_MACHINE_VERSIONS.json", "w") as file:  # pylint: disable=unspecified-encoding
        json.dump(versions, file)


def resolve_json_filenames(batch_file):
    """Return absolute json filenames from the batch manifest."""
    batch_dir = os.path.abspath(os.path.dirname(batch_file))
    with open(batch_file, "r") as fp:  # pylint: disable=unspecified-encoding
        data = json.load(fp)

    json_filenames = []
    for json_filename in data.get("json_filenames", []):
        if os.path.isabs(json_filename):
            json_filenames.append(json_filename)
        else:
            json_filenames.append(os.path.join(batch_dir, json_filename))
    return json_filenames


def close_active_project(oDesktop):
    """Close the active project if one exists."""
    oProject = oDesktop.GetActiveProject()
    if oProject is not None:
        oDesktop.CloseProject(oProject.GetName())


ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
scriptpath = os.path.dirname(__file__)

batchfile = ScriptArgument
jsonfiles = resolve_json_filenames(batchfile)

for jsonfile in jsonfiles:
    path = os.path.abspath(os.path.dirname(jsonfile))
    basename = os.path.splitext(os.path.basename(jsonfile))[0]

    with open(jsonfile, "r") as fp:  # pylint: disable=unspecified-encoding
        data = json.load(fp)
    simulation_flags = data["simulation_flags"]

    if data["ansys_tool"] == "cross-section":
        oDesktop.RunScriptWithArguments(os.path.join(scriptpath, "import_cross_section_geometry.py"), jsonfile)
    else:
        oDesktop.RunScriptWithArguments(os.path.join(scriptpath, "import_simulation_geometry.py"), jsonfile)

    if data.get("ansys_tool", "hfss") in ["q3d", "cross-section"] or data.get("capacitance_export", False):
        oDesktop.RunScript(os.path.join(scriptpath, "create_capacitive_pi_model.py"))

    oDesktop.RunScript(os.path.join(scriptpath, "create_reports.py"))
    oDesktop.TileWindows(0)

    oProject = oDesktop.GetActiveProject()
    oProject.SaveAs(os.path.join(path, basename + "_project.aedt"), True)

    if "pyepr" not in simulation_flags:
        oDesign = oProject.GetActiveDesign()
        oDesign.AnalyzeAll()
        oProject.Save()
        oDesktop.RunScript(os.path.join(scriptpath, "export_solution_data.py"))

        if "tdr" in simulation_flags:
            oDesktop.RunScript(os.path.join(scriptpath, "export_tdr.py"))

        if "snp_no_deembed" in simulation_flags:
            oDesktop.RunScript(os.path.join(scriptpath, "export_snp_no_deembed.py"))

    close_active_project(oDesktop)

write_simulation_machine_versions_file(oDesktop)
