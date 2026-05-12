"""EPR partition regions and correction cuts for DoublePadsSQNL."""

from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.epr.util import EPRTarget, create_bulk_and_mer_partition_regions
from kqcircuits.simulations.export.ansys.ansys_solution import AnsysCrossSectionSolution
from kqcircuits.simulations.partition_region import PartitionRegion


METAL_EDGE_DIMENSION = 3.0
ISLAND_GAP_SIDE_METAL_EDGE_DIMENSION = 6.0
VERTICAL_DIMENSION = 3.0
HALF_CUT_LENGTH = 30.0

ANSYS_CROSS_SECTION_MESH_SIZE = {
    "ma_layer_mer": 0.0005,
    "ms_layer_mer": 0.0005,
    "sa_layer_mer": 0.0005,
}


def _ansys_correction_solution() -> AnsysCrossSectionSolution:
    return AnsysCrossSectionSolution(
        percent_error=0.001,
        maximum_passes=20,
        integrate_energies=True,
        mesh_size=ANSYS_CROSS_SECTION_MESH_SIZE,
    )


def _sized_region(simulation: EPRTarget, polygon: pya.DPolygon, margin: float, radius: float = 0.0) -> pya.Region:
    region = pya.Region(polygon.to_itype(simulation.layout.dbu))
    if radius > 0.0:
        region.round_corners(radius / simulation.layout.dbu, radius / simulation.layout.dbu, simulation.n)
    if margin > 0.0:
        region = region.sized(round(margin / simulation.layout.dbu))
    return region


def _box_polygon(left: float, bottom: float, right: float, top: float) -> pya.DPolygon:
    left, right = sorted((left, right))
    bottom, top = sorted((bottom, top))
    return pya.DPolygon(
        [
            pya.DPoint(left, top),
            pya.DPoint(right, top),
            pya.DPoint(right, bottom),
            pya.DPoint(left, bottom),
        ]
    )


def _geometry(simulation: EPRTarget) -> dict[str, float | pya.DPoint]:
    base = simulation.refpoints["base"]
    upper_attach = simulation.refpoints["junction_attach_island_1"]
    lower_attach = simulation.refpoints["junction_attach_island_2"]

    attach_span = upper_attach.y - lower_attach.y
    if attach_span <= 0.0:
        raise ValueError("DoublePadsSQNL EPR correction expects upper attach point above lower attach point.")

    taper_height = (float(simulation.island_island_gap) - attach_span) / 2.0
    if taper_height <= 0.0:
        raise ValueError("DoublePadsSQNL island gap must exceed direct junction attach span.")

    island1_width = float(simulation.island1_extent[0])
    island1_height = float(simulation.island1_extent[1])
    island2_width = float(simulation.island2_extent[0])
    island2_height = float(simulation.island2_extent[1])
    coupler_width = float(simulation.coupler_extent[0])
    coupler_height = float(simulation.coupler_extent[1])

    island1_bottom = upper_attach.y + taper_height
    island1_top = island1_bottom + island1_height
    island2_top = lower_attach.y - taper_height
    island2_bottom = island2_top - island2_height
    coupler_bottom = island1_top + float(simulation.coupler_offset)
    coupler_top = coupler_bottom + coupler_height

    return {
        "base": base,
        "upper_attach": upper_attach,
        "lower_attach": lower_attach,
        "taper_height": taper_height,
        "island1_width": island1_width,
        "island1_height": island1_height,
        "island2_width": island2_width,
        "island2_height": island2_height,
        "island1_bottom": island1_bottom,
        "island1_top": island1_top,
        "island2_bottom": island2_bottom,
        "island2_top": island2_top,
        "coupler_width": coupler_width,
        "coupler_height": coupler_height,
        "coupler_bottom": coupler_bottom,
        "coupler_top": coupler_top,
    }


def _island_pad_region(simulation: EPRTarget, geom: dict[str, float | pya.DPoint]) -> pya.Region:
    base = geom["base"]
    region = pya.Region()
    region += _sized_region(
        simulation,
        _box_polygon(
            base.x - geom["island1_width"] / 2.0,
            geom["island1_bottom"],
            base.x + geom["island1_width"] / 2.0,
            geom["island1_top"],
        ),
        METAL_EDGE_DIMENSION,
        float(simulation.island1_r),
    )
    region += _sized_region(
        simulation,
        _box_polygon(
            base.x - geom["island2_width"] / 2.0,
            geom["island2_bottom"],
            base.x + geom["island2_width"] / 2.0,
            geom["island2_top"],
        ),
        METAL_EDGE_DIMENSION,
        float(simulation.island2_r),
    )
    region.merge()
    return region


def _taper_region(simulation: EPRTarget, geom: dict[str, float | pya.DPoint]) -> pya.Region:
    base = geom["base"]
    upper_attach = geom["upper_attach"]
    lower_attach = geom["lower_attach"]
    region = pya.Region()
    region += _sized_region(
        simulation,
        pya.DPolygon(
            [
                pya.DPoint(base.x + float(simulation.island1_taper_width) / 2.0, geom["island1_bottom"]),
                pya.DPoint(upper_attach.x + float(simulation.island1_taper_junction_width) / 2.0, upper_attach.y),
                pya.DPoint(upper_attach.x - float(simulation.island1_taper_junction_width) / 2.0, upper_attach.y),
                pya.DPoint(base.x - float(simulation.island1_taper_width) / 2.0, geom["island1_bottom"]),
            ]
        ),
        METAL_EDGE_DIMENSION,
    )
    region += _sized_region(
        simulation,
        pya.DPolygon(
            [
                pya.DPoint(base.x + float(simulation.island2_taper_width) / 2.0, geom["island2_top"]),
                pya.DPoint(lower_attach.x + float(simulation.island2_taper_junction_width) / 2.0, lower_attach.y),
                pya.DPoint(lower_attach.x - float(simulation.island2_taper_junction_width) / 2.0, lower_attach.y),
                pya.DPoint(base.x - float(simulation.island2_taper_width) / 2.0, geom["island2_top"]),
            ]
        ),
        METAL_EDGE_DIMENSION,
    )
    region.merge()
    return region


def _junction_gap_region(simulation: EPRTarget, geom: dict[str, float | pya.DPoint]) -> pya.Region:
    upper_attach = geom["upper_attach"]
    lower_attach = geom["lower_attach"]
    half_width = max(
        float(simulation.island1_taper_junction_width),
        float(simulation.island2_taper_junction_width),
    ) / 2.0
    return pya.Region(
        pya.DBox(
            upper_attach.x - half_width - METAL_EDGE_DIMENSION,
            lower_attach.y - METAL_EDGE_DIMENSION,
            upper_attach.x + half_width + METAL_EDGE_DIMENSION,
            upper_attach.y + METAL_EDGE_DIMENSION,
        ).to_itype(simulation.layout.dbu)
    )


def _coupler_feed_region(simulation: EPRTarget, geom: dict[str, float | pya.DPoint]) -> pya.Region:
    base = geom["base"]
    return _sized_region(
        simulation,
        _box_polygon(
            base.x - float(simulation.coupler_a) / 2.0,
            base.y + float(simulation.ground_gap[1]) / 2.0,
            base.x + float(simulation.coupler_a) / 2.0,
            geom["coupler_top"],
        ),
        METAL_EDGE_DIMENSION,
    )


def _coupler_paddle_region(simulation: EPRTarget, geom: dict[str, float | pya.DPoint]) -> pya.Region:
    base = geom["base"]
    return _sized_region(
        simulation,
        _box_polygon(
            base.x - geom["coupler_width"] / 2.0,
            geom["coupler_bottom"],
            base.x + geom["coupler_width"] / 2.0,
            geom["coupler_top"],
        ),
        METAL_EDGE_DIMENSION,
        float(simulation.coupler_r),
    )


def partition_regions(simulation: EPRTarget, prefix: str = "") -> list[PartitionRegion]:
    """Return DoublePadsSQNL EPR partition regions.

    Region order matters because KQCircuits subtracts earlier partition regions from later ones.
    Narrow junction/taper/coupler regions are placed before pad and complement regions.
    """

    geom = _geometry(simulation)
    face = simulation.face_ids[0]

    result = create_bulk_and_mer_partition_regions(
        name=f"{prefix}junctiongap",
        face=face,
        region=_junction_gap_region(simulation, geom),
        vertical_dimensions=VERTICAL_DIMENSION,
        metal_edge_dimensions=METAL_EDGE_DIMENSION,
        bulk=False,
        visualise=True,
    )
    result += create_bulk_and_mer_partition_regions(
        name=f"{prefix}taper",
        face=face,
        region=_taper_region(simulation, geom),
        vertical_dimensions=VERTICAL_DIMENSION,
        metal_edge_dimensions=METAL_EDGE_DIMENSION,
        bulk=False,
        visualise=True,
    )
    result += create_bulk_and_mer_partition_regions(
        name=f"{prefix}couplerfeed",
        face=face,
        region=_coupler_feed_region(simulation, geom),
        vertical_dimensions=VERTICAL_DIMENSION,
        metal_edge_dimensions=METAL_EDGE_DIMENSION,
        bulk=False,
        visualise=True,
    )
    result += create_bulk_and_mer_partition_regions(
        name=f"{prefix}couplerpaddle",
        face=face,
        region=_coupler_paddle_region(simulation, geom),
        vertical_dimensions=VERTICAL_DIMENSION,
        metal_edge_dimensions=METAL_EDGE_DIMENSION,
        bulk=False,
        visualise=True,
    )
    result += create_bulk_and_mer_partition_regions(
        name=f"{prefix}islandpad",
        face=face,
        region=_island_pad_region(simulation, geom),
        vertical_dimensions=VERTICAL_DIMENSION,
        metal_edge_dimensions=[ISLAND_GAP_SIDE_METAL_EDGE_DIMENSION, METAL_EDGE_DIMENSION],
        visualise=True,
    )
    result += create_bulk_and_mer_partition_regions(
        name=f"{prefix}{face}complement",
        face=face,
        region=None,
        vertical_dimensions=VERTICAL_DIMENSION,
        metal_edge_dimensions=METAL_EDGE_DIMENSION,
        visualise=True,
    )
    return result


def correction_cuts(simulation: EPRTarget, prefix: str = "") -> dict[str, dict]:
    """Return Ansys cross-section correction cuts for DoublePadsSQNL."""

    geom = _geometry(simulation)
    base = geom["base"]
    upper_attach = geom["upper_attach"]
    lower_attach = geom["lower_attach"]
    solution = _ansys_correction_solution

    taper_y = (upper_attach.y + geom["island1_bottom"]) / 2.0
    junction_cut_margin = max(10.0, 2.0 * METAL_EDGE_DIMENSION)
    coupler_feed_y = (geom["coupler_top"] + base.y + float(simulation.ground_gap[1]) / 2.0) / 2.0
    coupler_center_y = (geom["coupler_bottom"] + geom["coupler_top"]) / 2.0
    ground_gap_right = base + pya.DPoint(float(simulation.ground_gap[0]) / 2.0, 0)

    return {
        f"{prefix}junctiongapmer": {
            "p1": pya.DPoint(base.x, lower_attach.y - junction_cut_margin),
            "p2": pya.DPoint(base.x, upper_attach.y + junction_cut_margin),
            "solution": solution(),
        },
        f"{prefix}tapermer": {
            "p1": pya.DPoint(base.x - HALF_CUT_LENGTH, taper_y),
            "p2": pya.DPoint(base.x + HALF_CUT_LENGTH, taper_y),
            "solution": solution(),
        },
        f"{prefix}couplerfeedmer": {
            "p1": pya.DPoint(base.x - HALF_CUT_LENGTH, coupler_feed_y),
            "p2": pya.DPoint(base.x + HALF_CUT_LENGTH, coupler_feed_y),
            "solution": solution(),
        },
        f"{prefix}couplerpaddlemer": {
            "p1": pya.DPoint(base.x + geom["coupler_width"] / 4.0, coupler_center_y - HALF_CUT_LENGTH),
            "p2": pya.DPoint(base.x + geom["coupler_width"] / 4.0, coupler_center_y + HALF_CUT_LENGTH),
            "solution": solution(),
        },
        f"{prefix}islandpadmer": {
            "p1": pya.DPoint(base.x + geom["island1_width"] / 4.0, geom["island1_bottom"] - HALF_CUT_LENGTH),
            "p2": pya.DPoint(base.x + geom["island1_width"] / 4.0, geom["island1_bottom"] + HALF_CUT_LENGTH),
            "solution": solution(),
        },
        f"{prefix}{simulation.face_ids[0]}complementmer": {
            "p1": ground_gap_right + pya.DPoint(-HALF_CUT_LENGTH, 0),
            "p2": ground_gap_right + pya.DPoint(HALF_CUT_LENGTH, 0),
            "solution": solution(),
        },
    }
