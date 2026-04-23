"""Run pyEPR for a batch of imported eigenmode projects without restarting AEDT for every case."""
import json
import sys

from pathlib import Path

import pandas as pd
import pyEPR as epr
import qutip.fileio


def load_post_process_data(data_filename):
    """Load the pyEPR parameter file."""
    with open(data_filename, "r", encoding="utf-8") as fp:
        return json.load(fp)


def load_simulation_batch(manifest_filename):
    """Return simulation json filenames as absolute paths."""
    manifest_path = Path(manifest_filename).resolve()
    with open(manifest_path, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    json_filenames = []
    for filename in data.get("json_filenames", []):
        filename_path = Path(filename)
        json_filenames.append(filename_path if filename_path.is_absolute() else manifest_path.parent / filename_path)
    return json_filenames


def get_project_name(json_filename):
    """Return the AEDT project basename for a simulation json file."""
    return f"{Path(json_filename).stem}_project"


def run_pyepr_for_project(project_name, project_path, pp_data):
    """Run pyEPR for one already imported project."""
    epr.config["dissipation"].update(
        {
            "tan_delta_sapp": pp_data.get("substrate_loss_tangent", 1e-6),
            "tan_delta_surf": 0.001,
            "th": 3e-9,
            "eps_r": 10,
        }
    )

    correction_factor = {
        "layerMA": 1 / 2.5,
        "layerMS": 1 / 0.35,
        "layerSA": 1 / 0.7,
    }

    pinfo = epr.ProjectInfo(
        project_path=project_path,
        project_name=project_name,
        design_name="EigenmodeDesign",
    )

    try:
        junction_numbers = [int(entry.split("Junction")[-1]) for entry in pinfo.get_all_object_names() if "Junction" in entry]

        pinfo.dissipative["dielectrics_bulk"] = [entry for entry in pinfo.get_all_object_names() if entry.startswith("Substrate")]
        if pp_data.get("dielectric_surfaces", None) is None:
            pinfo.dissipative["dielectric_surfaces"] = [
                entry
                for entry in pinfo.get_all_object_names()
                if not (
                    entry.startswith("Vacuum")
                    or entry.startswith("Substrate")
                    or any(entry in [f"Port{index}", f"Junction{index}"] for index in junction_numbers)
                )
            ]
        else:
            pinfo.dissipative["dielectric_surfaces"] = {
                entry: value
                for entry in pinfo.get_all_object_names()
                for layer_name, value in pp_data["dielectric_surfaces"].items()
                if layer_name in entry
            }

        oEditor = pinfo.design.modeler._modeler
        for junction_number in junction_numbers:
            line_name = f"Junction{junction_number}"
            pinfo.junctions[f"j{junction_number}"] = {
                "Lj_variable": f"Lj_{junction_number}",
                "rect": f"Port{junction_number}",
                "line": line_name,
                "Cj_variable": f"Cj_{junction_number}",
                "length": (
                    f"{oEditor.GetEdgeLength(oEditor.GetEdgeIDsFromObject(line_name)[0])}{oEditor.GetModelUnits()}"
                ),
            }
        pinfo.validate_junction_info()

        if pinfo.setup.solution_name:
            pinfo.setup.analyze()

        eprh = epr.DistributedAnalysis(pinfo)
        eprh.do_EPR_analysis()

        epra = epr.QuantumAnalysis(eprh.data_filename)
        epr_results = epra.analyze_all_variations()

        df = pd.DataFrame()
        for variation, data in epr_results.items():
            f_ND, chi_ND, hamiltonian = epr.calcs.back_box_numeric.epr_numerical_diagonalization(
                data["f_0"] / 1e3,
                data["Ljs"],
                data["ZPF"],
                return_H=True,
            )
            qutip.fileio.qsave(hamiltonian, str(project_path / f"Hamiltonian_{project_name}_{variation}.qu"))

            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        {
                            "variation": eprh.get_variation_string(variation),
                            **{
                                (Q_bulk := data["sol"].filter(regex=bulk + "$")).columns[0]: Q_bulk.values.flatten()
                                for bulk in pinfo.dissipative["dielectrics_bulk"]
                            },
                            **{
                                f"p_dielectric_{bulk}": (
                                    1 / (data["sol"].filter(regex=bulk + "$") * epr.config["dissipation"]["tan_delta_sapp"])
                                ).values.flatten()
                                for bulk in pinfo.dissipative["dielectrics_bulk"]
                            },
                            **{
                                (Q_surf := data["sol"].filter(regex=surface)).columns[0]: Q_surf.values.flatten()
                                / correction_factor.get(surface, 1)
                                for surface in pinfo.dissipative["dielectric_surfaces"].keys()
                            },
                            **{
                                f"p_surf_{surface}": (
                                    1
                                    / (
                                        data["sol"].filter(regex=surface)
                                        * (
                                            pinfo.dissipative["dielectric_surfaces"][surface]["tan_delta_surf"]
                                            if isinstance(pinfo.dissipative["dielectric_surfaces"], dict)
                                            else epr.config["dissipation"]["tan_delta_surf"]
                                        )
                                        * correction_factor.get(surface, 1)
                                    )
                                ).values.flatten()
                                for surface in pinfo.dissipative["dielectric_surfaces"].keys()
                            },
                            "Q_ansys": data.get("Qs", None),
                            "f_0": data["f_0"] * 1e6,
                            "f_1": data["f_1"] * 1e6,
                            "ZPF": data["ZPF"].flatten(),
                            "Pm_normed": data["Pm_normed"].flatten(),
                            "Ljs": data["Ljs"][0],
                            "Cjs": data["Cjs"][0],
                            "Chi_O1": str(data["chi_O1"].values),
                            "Chi_ND": str(chi_ND),
                            "f_ND": f_ND,
                        }
                    ).rename_axis("mode"),
                ]
            )

            df["Q_total"] = (1 / (1 / df.filter(regex="^Q(dielectric|surf).*")).sum(axis=1)).values.flatten()

        df.set_index(["variation", df.index], inplace=True)
        df.to_csv(project_path / f"QData_{project_name}.csv", index_label=["variation", "mode"])
        pinfo.project.save()
    finally:
        pinfo.disconnect()


def main():
    """CLI entry point for the batch pyEPR flow."""
    manifest_filename = Path(sys.argv[1]).resolve()
    pp_data = load_post_process_data(sys.argv[2])
    json_filenames = load_simulation_batch(manifest_filename)
    project_path = manifest_filename.parent
    desktop = None

    try:
        for index, json_filename in enumerate(json_filenames, start=1):
            project_name = get_project_name(json_filename)
            print(f"pyEPR batch {index}/{len(json_filenames)}: {project_name}")
            run_pyepr_for_project(project_name, project_path, pp_data)
            desktop = epr.ansys.HfssApp().get_app_desktop()._desktop
            desktop.CloseProject(project_name)
    finally:
        if desktop is None:
            desktop = epr.ansys.HfssApp().get_app_desktop()._desktop
        desktop.QuitApplication()


if __name__ == "__main__":
    main()
