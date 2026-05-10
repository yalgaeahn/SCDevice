"""Produce SCDevice transmon target report from KQ capacitance matrix results."""

import argparse
import csv
import json
import math
from pathlib import Path


REPORT_CSV = "transmon_target_report.csv"
CASE_CSV = "capacitance_cases.csv"
RESULT_SUFFIX = "_project_results.json"

ELEMENTARY_CHARGE_C = 1.602176634e-19
PLANCK_CONSTANT_J_S = 6.62607015e-34
FEMTO = 1e-15


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as file:
        return json.load(file)


def read_csv_by_name(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        return {row["name"]: row for row in csv.DictReader(file)}


def write_csv(path, rows):
    if not rows:
        raise ValueError("No transmon target rows were produced.")
    fieldnames = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ff(value):
    return float(value) / FEMTO


def format_float(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    try:
        return f"{float(value):.10g}"
    except (TypeError, ValueError):
        return value


def get_metadata(definition):
    return definition.get("parameters", {}).get("extra_json_data", {})


def estimate_transmon_frequencies(c_sigma_fF, ej_GHz):
    if c_sigma_fF <= 0 or ej_GHz <= 0:
        return {}
    c_sigma_F = c_sigma_fF * FEMTO
    ec_GHz = ELEMENTARY_CHARGE_C**2 / (
        2 * PLANCK_CONSTANT_J_S * c_sigma_F
    ) / 1e9
    fge_GHz = math.sqrt(8 * ej_GHz * ec_GHz) - ec_GHz
    return {
        "estimated_Ec_GHz": ec_GHz,
        "estimated_fge_GHz": fge_GHz,
        "estimated_fef_GHz": fge_GHz - ec_GHz,
        "estimated_fgf_over_2_GHz": fge_GHz - ec_GHz / 2,
        "estimated_anharmonicity_GHz": ec_GHz,
    }


def symmetric_entry(matrix_fF, row, col):
    if row == col:
        return matrix_fF[row][col]
    return (matrix_fF[row][col] + matrix_fF[col][row]) / 2


def capacitance_metrics(matrix, junction_capacitance_fF):
    matrix_fF = [[ff(value) for value in row] for row in matrix]
    if len(matrix_fF) < 2:
        raise ValueError("Transmon target report needs at least two signal nets.")

    upper = 0
    lower = 2 if len(matrix_fF) >= 3 else 1
    grounded = [index for index in range(len(matrix_fF)) if index not in (upper, lower)]

    upper_self = symmetric_entry(matrix_fF, upper, upper)
    lower_self = symmetric_entry(matrix_fF, lower, lower)
    island_mutual = symmetric_entry(matrix_fF, upper, lower)
    upper_to_grounded = upper_self + sum(
        symmetric_entry(matrix_fF, upper, index) for index in grounded
    )
    lower_to_grounded = lower_self + sum(
        symmetric_entry(matrix_fF, lower, index) for index in grounded
    )

    if upper_to_grounded + lower_to_grounded:
        shunt_series = (
            upper_to_grounded
            * lower_to_grounded
            / (upper_to_grounded + lower_to_grounded)
        )
    else:
        shunt_series = 0.0

    c_sigma = island_mutual + shunt_series + junction_capacitance_fF
    metrics = {
        "c_sigma_fF": c_sigma,
        "c_sigma_model": "pi_floating_pair_grounded_non_qubit_nets",
        "c_sigma_self_avg_fF": (upper_self + lower_self) / 2
        + junction_capacitance_fF,
        "c_upper_self_fF": upper_self,
        "c_lower_self_fF": lower_self,
        "c_island_island_mutual_fF": island_mutual,
        "c_upper_to_grounded_nets_fF": upper_to_grounded,
        "c_lower_to_grounded_nets_fF": lower_to_grounded,
        "junction_capacitance_fF": junction_capacitance_fF,
        "matrix_size": len(matrix_fF),
    }
    if grounded:
        first_grounded = grounded[0]
        metrics["c_upper_to_coupler_mutual_fF"] = symmetric_entry(
            matrix_fF, upper, first_grounded
        )
        metrics["c_lower_to_coupler_mutual_fF"] = symmetric_entry(
            matrix_fF, lower, first_grounded
        )
    return metrics


def make_report_rows(path):
    case_rows = read_csv_by_name(path / CASE_CSV)
    rows = []
    for result_path in sorted(path.glob(f"*{RESULT_SUFFIX}")):
        name = result_path.name[: -len(RESULT_SUFFIX)]
        definition_path = path / f"{name}.json"
        if not definition_path.exists():
            print(f"WARNING: missing simulation definition for {result_path.name}")
            continue

        result = load_json(result_path)
        definition = load_json(definition_path)
        metadata = get_metadata(definition)
        target_c_sigma = float(metadata.get("target_C_sigma_fF", 0.0))
        target_ej = float(metadata.get("target_EJ_GHz", 0.0))
        junction_capacitance = float(metadata.get("junction_capacitance_fF", 0.0))

        metrics = capacitance_metrics(result["CMatrix"], junction_capacitance)
        estimates = estimate_transmon_frequencies(metrics["c_sigma_fF"], target_ej)
        target_error = metrics["c_sigma_fF"] - target_c_sigma
        self_avg_error = metrics["c_sigma_self_avg_fF"] - target_c_sigma

        row = {
            "name": name,
            **case_rows.get(name, {}),
            "target_C_sigma_fF": target_c_sigma,
            "target_error_fF": target_error,
            "target_error_pct": 100 * target_error / target_c_sigma
            if target_c_sigma
            else "",
            "within_8fF": abs(target_error) <= 8.0,
            "self_avg_error_fF": self_avg_error,
            "self_avg_error_pct": 100 * self_avg_error / target_c_sigma
            if target_c_sigma
            else "",
            **metrics,
            **estimates,
            "target_Ec_GHz": metadata.get("target_Ec_GHz", ""),
            "target_EJ_GHz": metadata.get("target_EJ_GHz", ""),
            "target_fge_GHz": metadata.get("target_fge_GHz", ""),
            "target_fef_GHz": metadata.get("target_fef_GHz", ""),
            "target_fgf_over_2_GHz": metadata.get("target_fgf_over_2_GHz", ""),
            "target_anharmonicity_GHz": metadata.get(
                "target_anharmonicity_GHz", ""
            ),
            "result_file": result_path.name,
        }
        rows.append({key: format_float(value) for key, value in row.items()})
    return rows


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    path = args.path.resolve()
    output = args.output or path / REPORT_CSV
    write_csv(output, make_report_rows(path))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
