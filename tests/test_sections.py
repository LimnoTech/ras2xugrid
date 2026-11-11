"""Cross-section faces and series on the synthetic plan."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest
import shapely

import ras2xugrid
from ras2xugrid import (
    boundary_faces,
    cross_section_faces,
    cross_section_series,
    faces_from_table,
    open_flow_area,
)
from ras2xugrid.sections import _check_chain

pytestmark = pytest.mark.filterwarnings("ignore:skipped 'Courant Number Max'")


@pytest.fixture
def uds(synthetic_plan):
    return open_flow_area(synthetic_plan)


def test_public_names():
    assert ras2xugrid.__all__ == [
        "list_flow_areas",
        "open_flow_area",
        "pipe_nodes",
        "boundary_faces",
        "faces_from_table",
        "cross_section_faces",
        "cross_section_series",
    ]
    assert ras2xugrid.__version__


def test_boundary_of_two_cells_drops_their_shared_face(uds):
    faces = boundary_faces(uds, {"pair": [0, 1]})
    assert faces.index.names == ["cross_section", "edge"]
    assert faces["sign"].dtype == "int8"
    assert list(faces.index.get_level_values("edge")) == [1, 2, 3, 4, 12, 13]
    assert list(faces["sign"]) == [-1, 1, 1, 1, 1, 1]


def _jasons_table():
    # (face, US_Cell) for every face of c0 and c1; f0 is shared, so it
    # appears twice with opposite signs, and f1's first cell is c2, so
    # c1 gives it -1
    rows = [(0, 0), (3, 0), (12, 0), (13, 0), (0, 1), (1, 1), (2, 1), (4, 1)]
    return pd.DataFrame(
        {
            "CrossSection": "pair",
            "Face": [f for f, _ in rows],
            "US_Cell": [c for _, c in rows],
        }
    )


def test_boundary_matches_jasons_us_cell_rule(uds):
    expected = boundary_faces(uds, {"pair": [0, 1]})
    from_table = faces_from_table(uds, _jasons_table())
    pd.testing.assert_frame_equal(from_table, expected)
    a = cross_section_series(uds, from_table)
    b = cross_section_series(uds, expected)
    assert a.equals(b)


def test_series_is_the_signed_sum(uds):
    series = cross_section_series(uds, boundary_faces(uds, {"pair": [0, 1]}))
    assert series["Face Flow"].dims == ("time", "cross_section")
    for t in range(3):
        assert series["Face Flow"].values[t, 0] == (t + 1) * (-2 + 3 + 4 + 5 + 13 + 14)
    assert series["Face Flow"].attrs["Units"] == "cfs"
    assert series["Face Flow"].attrs["derivation"] == (
        "sum over the cross section's faces of sign × Face Flow"
    )
    assert "Face Cumulative Volume" in series
    assert "time" in series.coords and "time_days" in series.coords
    assert series["time_days"].attrs["Time"] == "days"
    assert series["time_days"].attrs["hecras_name"] == "Time"


def test_sections_are_named_and_ordered(uds):
    series = cross_section_series(uds, boundary_faces(uds, {"b": [3], "a": [0]}))
    assert list(series["cross_section"].values) == ["b", "a"]


@pytest.mark.parametrize("index", [-1, 4, 99])
def test_a_cell_index_that_is_not_a_real_cell_raises(uds, index):
    with pytest.raises(ValueError, match="outlet"):
        boundary_faces(uds, {"outlet": [index]})


def test_an_empty_section_raises(uds):
    with pytest.raises(ValueError, match="outlet"):
        boundary_faces(uds, {"outlet": []})


def test_a_table_row_whose_us_cell_is_not_on_the_face_raises(uds):
    table = pd.DataFrame({"CrossSection": ["x"], "Face": [0], "US_Cell": [3]})
    with pytest.raises(ValueError, match="row 0"):
        faces_from_table(uds, table)


def test_a_variable_not_on_faces_raises(uds):
    with pytest.raises(ValueError, match="Water Surface"):
        cross_section_series(
            uds, boundary_faces(uds, {"a": [0]}), variables=("Water Surface",)
        )


def test_a_ghost_side_counts_as_outside(uds):
    faces = boundary_faces(uds, {"c3": [3]})
    assert list(faces.index.get_level_values("edge")) == [2, 8, 9, 10, 11]
    assert list(faces["sign"]) == [-1, 1, 1, 1, 1]
    assert np.all(faces["sign"].isin([-1, 1]))


def _frame(rows):
    index = pd.MultiIndex.from_tuples(
        [(s, e) for s, e, _ in rows], names=["cross_section", "edge"]
    )
    return pd.DataFrame(
        {"sign": np.array([r[2] for r in rows], dtype="int8")}, index=index
    )


def test_a_nan_in_one_section_leaves_the_others_exact(uds):
    uds.obj["Face Flow"].values[:, 1] = np.nan
    faces = boundary_faces(uds, {"a": [0, 1], "b": [3]})  # a holds edge 1, b does not
    series = cross_section_series(uds, faces, variables=("Face Flow",))
    assert np.isnan(series["Face Flow"].sel(cross_section="a").values).all()
    # b: edges 2 (-1), 8, 9, 10, 11 (+1) ->
    # (t + 1) * (-3 + 9 + 10 + 11 + 12)
    expected = (np.arange(3) + 1) * (-3 + 9 + 10 + 11 + 12)
    assert (series["Face Flow"].sel(cross_section="b").values == expected).all()


def test_multi_section_series_value_by_value(uds):
    faces = _frame([("x", 0, 1), ("x", 5, -1), ("y", 2, 1), ("y", 7, 1), ("y", 9, -1)])
    series = cross_section_series(
        uds, faces, variables=("Face Flow", "Face Cumulative Volume")
    )
    t = np.arange(3)
    flow_x = (t + 1) * (1 - 6)
    flow_y = (t + 1) * (3 + 8 - 10)
    assert (series["Face Flow"].values[:, 0] == flow_x).all()
    assert (series["Face Flow"].values[:, 1] == flow_y).all()
    volume_y = np.cumsum(flow_y * 43200)
    assert np.allclose(series["Face Cumulative Volume"].values[:, 1], volume_y)


def test_a_duplicate_section_edge_raises(uds):
    faces = _frame([("x", 0, 1), ("x", 0, 1)])
    with pytest.raises(ValueError, match="'x'.*edge 0"):
        cross_section_series(uds, faces)


@pytest.mark.parametrize("us_cell", [-1, 4, 99])
def test_a_us_cell_that_is_not_a_real_cell_raises(uds, us_cell):
    table = pd.DataFrame({"CrossSection": ["x"], "Face": [3], "US_Cell": [us_cell]})
    with pytest.raises(ValueError, match="row 0.*US_Cell"):
        faces_from_table(uds, table)


def test_a_missing_value_in_the_table_raises_naming_the_row(uds):
    table = pd.DataFrame(
        {"CrossSection": ["x", "x"], "Face": [0, np.nan], "US_Cell": [0, 1]}
    )
    with pytest.raises(ValueError, match="row 1"):
        faces_from_table(uds, table)


def test_the_same_side_listed_twice_raises(uds):
    table = pd.DataFrame(
        {"CrossSection": ["x", "x"], "Face": [0, 0], "US_Cell": [0, 0]}
    )
    with pytest.raises(ValueError, match="'x'.*Face 0"):
        faces_from_table(uds, table)


def test_a_face_listed_once_from_its_second_cell_is_minus_one(uds):
    table = pd.DataFrame({"CrossSection": ["x"], "Face": [1], "US_Cell": [1]})
    faces = faces_from_table(uds, table)
    assert list(faces["sign"]) == [-1]


def test_a_ghost_on_the_first_side_gives_minus_one(synthetic_plan):
    import h5py

    from ras2xugrid._hdf import GEOMETRY

    with h5py.File(synthetic_plan, "r+") as file:
        cells = file[f"{GEOMETRY}/meshArea/Faces Cell Indexes"]
        cells[3] = (4, 0)  # face 3: ghost first, cell 0 second
    uds = open_flow_area(synthetic_plan)
    faces = boundary_faces(uds, {"c0": [0]})
    assert faces["sign"].loc[("c0", 3)] == -1


def test_an_empty_faces_frame_raises_value_error(uds):
    faces = boundary_faces(uds, {"pair": [0, 1]}).iloc[:0]
    with pytest.raises(ValueError, match="no faces"):
        cross_section_series(uds, faces)


def test_a_non_integral_face_or_cell_is_refused_naming_the_row(uds):
    table = pd.DataFrame({"CrossSection": ["a"], "Face": [1.5], "US_Cell": [0]})
    with pytest.raises(ValueError, match=r"row 0.*Face 1.5"):
        faces_from_table(uds, table)
    table = pd.DataFrame({"CrossSection": ["a"], "Face": [0], "US_Cell": [0.5]})
    with pytest.raises(ValueError, match=r"row 0.*US_Cell 0.5"):
        faces_from_table(uds, table)
    table = pd.DataFrame({"CrossSection": ["a"], "Face": [0.0], "US_Cell": [0.0]})
    assert list(faces_from_table(uds, table).index.get_level_values("edge")) == [0]


def test_a_subset_dataset_is_refused_by_boundary_faces_and_series(uds):
    # Faces Cell Indexes is a data variable: a spatial subset keeps the
    # old numbering
    sub = uds.ugrid.sel(x=slice(0.9, 3.1))
    with pytest.raises(ValueError, match="no longer matches its grid"):
        boundary_faces(sub, {"a": [0]})
    faces = boundary_faces(uds, {"pair": [0, 1]})
    with pytest.raises(ValueError, match="no longer matches its grid"):
        faces_from_table(
            sub, pd.DataFrame({"CrossSection": ["a"], "Face": [0], "US_Cell": [0]})
        )
    with pytest.raises(ValueError, match="no longer matches its grid"):
        cross_section_series(sub, faces)


def test_a_dataset_without_faces_cell_indexes_is_refused(uds):
    without = uds[["Face Flow"]]
    with pytest.raises(ValueError, match="open_flow_area returned"):
        boundary_faces(without, {"a": [0]})
    faces = boundary_faces(uds, {"pair": [0, 1]})
    with pytest.raises(ValueError, match="open_flow_area returned"):
        cross_section_series(without, faces)


def _signs(faces, name):
    section = faces.loc[name]
    return dict(zip(section.index.tolist(), section["sign"].tolist(), strict=True))


def _line(*points):
    return shapely.LineString(points)


def test_the_plans_line_selects_face_0_only(uds):
    """Face 11 is the pentagon's perimeter face, (3, ghost), which is
    never selected.

    The line (1.05, -0.5) to (1.05, 1.5) crosses faces 0 and 11, but
    xugrid's snapping skips an edge whose other cell is a ghost, so only
    face 0 remains (its first cell, c0, is on the left of a line heading
    north: +1).
    """
    faces = cross_section_faces(uds, {"u": _line((1.05, -0.5), (1.05, 1.5))})
    assert faces.index.names == ["cross_section", "edge"]
    assert faces["sign"].dtype == "int8"
    assert _signs(faces, "u") == {0: 1}
    reversed_faces = cross_section_faces(uds, {"u": _line((1.05, 1.5), (1.05, -0.5))})
    assert _signs(reversed_faces, "u") == {0: -1}


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        (((0.3, -0.5), (2.7, 2.0)), {0: 1, 2: -1}),
        (((1.05, -0.5), (1.05, 0.9), (1.95, 0.9), (1.95, -0.5)), {0: 1, 1: 1, 2: -1}),
        (((1.0, -0.5), (1.0, 1.5)), {0: 1}),
        (((0.6, 1.5), (1.4, 0.5)), {0: -1}),
    ],
)
def test_lines_select_the_measured_faces_and_reversing_flips_every_sign(
    uds, points, expected
):
    # the U line has face 1, listed (2, 1), at +1: the sign follows the
    #   face's first cell
    # the line along x = 1 selects face 0 from both of its cells, which
    #   collapse
    # the last line passes through face point 5
    faces = cross_section_faces(uds, {"s": _line(*points)})
    assert _signs(faces, "s") == expected
    flipped = cross_section_faces(uds, {"s": _line(*points[::-1])})
    assert _signs(flipped, "s") == {edge: -sign for edge, sign in expected.items()}


def test_a_line_whose_faces_have_a_gap_raises_naming_the_section(uds):
    line = _line((1.05, 0.6), (1.05, -0.5), (1.95, -0.5), (1.95, 0.6))
    with pytest.raises(ValueError, match="'gappy'.*gap"):
        cross_section_faces(uds, {"gappy": line})


def test_a_line_that_crosses_no_face_raises_naming_the_section(uds):
    with pytest.raises(ValueError, match="'far'.*crosses no face"):
        cross_section_faces(uds, {"far": _line((5, 5), (6, 6))})


def test_a_line_inside_one_cell_raises_naming_the_section(uds):
    with pytest.raises(ValueError, match="'inside'.*selects no face"):
        cross_section_faces(uds, {"inside": _line((0.2, 0.2), (0.4, 0.4))})


def test_a_line_across_a_face_both_ways_raises_naming_the_section_and_edge(uds):
    # a V inside c0 and c1: the first leg has c1's centroid on its right
    # and the second on its left, so face 2 (between c1 and c3),
    # selected from c1 by both, gets opposite signs
    line = _line((0.5, 0.6), (1.5, 0.6), (0.5, 0.9))
    with pytest.raises(ValueError, match="'zig'.*edge 2"):
        cross_section_faces(uds, {"zig": line})


def test_a_lines_series_equals_the_tables(uds):
    faces = cross_section_faces(
        uds, {"u": _line((1.05, -0.5), (1.05, 0.9), (1.95, 0.9), (1.95, -0.5))}
    )
    # US_Cell is the face's cell on the line's left: c0 for f0
    # (cells 0, 1), c2 for f1 (cells 2, 1) and c3 for f2 (cells 1, 3)
    table = pd.DataFrame({"CrossSection": "u", "Face": [0, 1, 2], "US_Cell": [0, 2, 3]})
    from_table = faces_from_table(uds, table)
    pd.testing.assert_frame_equal(faces, from_table)
    assert cross_section_series(uds, faces).equals(
        cross_section_series(uds, from_table)
    )


def test_several_lines_keep_input_order(uds):
    faces = cross_section_faces(
        uds,
        {"b": _line((0.3, -0.5), (2.7, 2.0)), "a": _line((1.05, -0.5), (1.05, 1.5))},
    )
    assert list(dict.fromkeys(faces.index.get_level_values("cross_section"))) == [
        "b",
        "a",
    ]
    assert _signs(faces, "b") == {0: 1, 2: -1}
    assert _signs(faces, "a") == {0: 1}


def test_a_geodataframe_gives_the_same_frame(uds):
    gpd = pytest.importorskip("geopandas")
    line = _line((0.3, -0.5), (2.7, 2.0))
    expected = cross_section_faces(uds, {"s": line})
    gdf = gpd.GeoDataFrame({"geometry": [line]}, index=["s"], crs=uds.grid.crs)
    pd.testing.assert_frame_equal(cross_section_faces(uds, gdf), expected)
    other = gpd.GeoDataFrame({"geometry": [line]}, index=["s"], crs="EPSG:4326")
    with pytest.raises(ValueError, match="EPSG:4326"):
        cross_section_faces(uds, other)


def test_a_dataframe_with_a_geometry_column_needs_no_geopandas(uds):
    line = _line((0.3, -0.5), (2.7, 2.0))
    frame = pd.DataFrame({"geometry": [line]}, index=["s"])
    pd.testing.assert_frame_equal(
        cross_section_faces(uds, frame), cross_section_faces(uds, {"s": line})
    )


def test_max_distance_moves_vertices_onto_face_points(uds):
    # the end (1.03, 0.97) is 0.042 from face point 5 (1, 1): unmoved,
    #   the line crosses face 0;
    # moved onto the face point it ends there, inside c0, and selects
    #   nothing
    # it starts at c0's centroid, which is on the line, with c1 on its
    #   right: c0 is the left cell
    line = _line((0.5, 0.5), (1.03, 0.97))
    assert _signs(cross_section_faces(uds, {"s": line}), "s") == {0: 1}
    assert _signs(cross_section_faces(uds, {"s": line}, max_distance=0.0), "s") == {
        0: 1
    }
    with pytest.raises(ValueError, match="'s'.*selects no face"):
        cross_section_faces(uds, {"s": line}, max_distance=0.05)


def test_a_line_that_crosses_no_face_once_snapped_raises_naming_the_section(uds):
    # unmoved it enters the pentagon over perimeter face 11; moved onto
    # face point 5 it stays outside the mesh and crosses no face, where
    # xugrid itself would crash
    line = _line((0.5, 1.5), (1.04, 1.02))
    with pytest.raises(ValueError, match="'s'.*crosses no face once"):
        cross_section_faces(uds, {"s": line}, max_distance=0.05)


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_a_bad_max_distance_raises(uds, bad):
    with pytest.raises(ValueError, match="max_distance"):
        cross_section_faces(uds, {"s": _line((0, 0), (1, 1))}, max_distance=bad)


def test_bad_lines_are_refused_naming_the_section(uds):
    with pytest.raises(TypeError, match="'m'"):
        cross_section_faces(uds, {"m": shapely.MultiLineString([[(0, 0), (1, 1)]])})
    with pytest.raises(TypeError, match="'p'"):
        cross_section_faces(uds, {"p": shapely.Point(1, 1)})
    with pytest.raises(TypeError, match="'r'"):
        cross_section_faces(uds, {"r": shapely.LinearRing([(0, 0), (1, 0), (1, 1)])})
    with pytest.raises(ValueError, match="'z'"):
        cross_section_faces(uds, {"z": _line((1, 1), (1, 1))})
    with pytest.raises(ValueError, match="no lines"):
        cross_section_faces(uds, {})


def test_duplicate_names_and_a_missing_geometry_column_raise(uds):
    line = _line((0.3, -0.5), (2.7, 2.0))
    frame = pd.DataFrame({"geometry": [line, line]}, index=[1, "1"])
    with pytest.raises(ValueError, match="'1'"):
        cross_section_faces(uds, frame)
    with pytest.raises(ValueError, match="geometry"):
        cross_section_faces(uds, pd.DataFrame({"x": [1]}))


def test_the_chain_helper_names_a_branch_a_loop_and_a_gap():
    assert _check_chain("ok", np.array([[0, 1], [1, 2], [2, 3]])) is None
    with pytest.raises(ValueError, match="'y'.*branch"):
        _check_chain("y", np.array([[0, 1], [0, 2], [0, 3]]))
    with pytest.raises(ValueError, match="'ring'.*loop.*boundary_faces"):
        _check_chain("ring", np.array([[0, 1], [1, 2], [2, 0]]))
    with pytest.raises(ValueError, match="'two'.*gap"):
        _check_chain("two", np.array([[0, 1], [2, 3]]))


def test_a_subset_dataset_is_refused_by_cross_section_faces(uds):
    sub = uds.ugrid.sel(x=slice(0.9, 3.1))
    with pytest.raises(ValueError, match="no longer matches its grid"):
        cross_section_faces(sub, {"s": _line((0.3, -0.5), (2.7, 2.0))})


def test_a_lines_faces_are_boundary_faces_of_the_cells_on_its_left(uds):
    # the line x = 1.05 heading north has c0 on its left; c0's boundary
    # also holds perimeter faces, which a line never selects, so compare
    # on the line's own faces
    line_faces = cross_section_faces(uds, {"L": _line((1.05, -0.5), (1.05, 1.5))})
    boundary = boundary_faces(uds, {"L": [0]}).loc[["L"]]
    pd.testing.assert_frame_equal(boundary.loc[line_faces.index], line_faces)
    # the U line: left cells c0 (f0), c2 (f1) and c3 (f2)
    u = cross_section_faces(
        uds, {"L": _line((1.05, -0.5), (1.05, 0.9), (1.95, 0.9), (1.95, -0.5))}
    )
    boundary = boundary_faces(uds, {"L": [0, 2, 3]}).loc[["L"]]
    pd.testing.assert_frame_equal(boundary.loc[u.index], u)


@pytest.mark.parametrize("bad", [[(0, 0), (1, 1)], "a line", 5])
def test_lines_of_the_wrong_kind_raise_type_error(uds, bad):
    with pytest.raises(TypeError, match="lines must be"):
        cross_section_faces(uds, bad)


@pytest.mark.parametrize("bad", ["1.0", [1.0], True])
def test_a_non_numeric_max_distance_raises_type_error(uds, bad):
    with pytest.raises(TypeError, match="max_distance"):
        cross_section_faces(uds, {"s": _line((0, 0), (1, 1))}, max_distance=bad)


def test_a_centroid_on_the_line_gets_the_sign_of_the_cells_on_either_side(uds):
    # c0's centroid (0.5, 0.5) is the line's start; xugrid's lengthened
    # segment puts it on a side, the exact line does not, so the sign
    # compares the face's two cells instead
    points = ((0.5, 0.5), (1.6, 0.8))
    faces = cross_section_faces(uds, {"s": _line(*points)})
    assert _signs(faces, "s") == {0: 1, 2: -1}
    flipped = cross_section_faces(uds, {"s": _line(*points[::-1])})
    assert _signs(flipped, "s") == {0: -1, 2: 1}


def _consistent_sides(uds, faces, name):
    """Whether one left/right labelling of cells fits every sign of the
    section."""
    face_cells = np.asarray(uds["Faces Cell Indexes"].values)
    left: dict[int, bool] = {}
    for edge, sign in _signs(faces, name).items():
        first, second = (int(c) for c in face_cells[edge])
        for cell, is_left in ((first, sign == 1), (second, sign == -1)):
            if left.setdefault(cell, is_left) != is_left:
                return False
    return True


_DOCUMENTED_REFUSALS = (
    r"crosses no face|selects no face|have a gap|the faces branch|closed loop|both ways"
)


def test_every_line_between_centroids_has_signs_that_fit_one_left_and_right(uds):
    centroids = np.asarray(uds.grid.centroids)
    outside = [(-0.7, 0.2), (3.4, 1.3), (1.5, 2.2), (2.0, -0.9)]
    points = [tuple(p) for p in centroids] + outside
    checked = 0
    for start in points:
        for end in points:
            if start == end:
                continue
            for line in (_line(start, end), _line(end, start)):
                try:
                    faces = cross_section_faces(uds, {"s": line})
                except ValueError as error:
                    assert re.search(_DOCUMENTED_REFUSALS, str(error)), (
                        start,
                        end,
                        str(error),
                    )
                    continue
                assert _consistent_sides(uds, faces, "s"), (start, end)
                checked += 1
    assert checked > 20


def test_a_series_of_lines_is_read_like_a_frame(uds):
    line = _line((0.3, -0.5), (2.7, 2.0))
    expected = cross_section_faces(uds, {"s": line})
    series = pd.Series([line], index=["s"])
    pd.testing.assert_frame_equal(cross_section_faces(uds, series), expected)


def test_a_geoseries_of_lines_checks_its_crs(uds):
    gpd = pytest.importorskip("geopandas")
    line = _line((0.3, -0.5), (2.7, 2.0))
    expected = cross_section_faces(uds, {"s": line})
    series = gpd.GeoSeries([line], index=["s"], crs=uds.grid.crs)
    pd.testing.assert_frame_equal(cross_section_faces(uds, series), expected)
    other = gpd.GeoSeries([line], index=["s"], crs="EPSG:4326")
    with pytest.raises(ValueError, match="EPSG:4326"):
        cross_section_faces(uds, other)
