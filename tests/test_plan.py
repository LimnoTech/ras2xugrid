"""``list_flow_areas``, ``open_flow_area`` and ``pipe_nodes`` on the synthetic plan."""

from __future__ import annotations

import h5py
import numpy as np
import pandas as pd
import pytest
import xarray as xr
import xugrid as xu

from ras2xugrid import testing
from ras2xugrid._hdf import GEOMETRY, RESULTS, parse_time_date_stamp
from ras2xugrid.plan import list_flow_areas, open_flow_area, pipe_nodes

# The synthetic plan's "Courant Number Max" has no Location on purpose; tests that care say so.
pytestmark = pytest.mark.filterwarnings("ignore:skipped 'Courant Number Max'")


def test_list_flow_areas_reads_counts_and_titles(synthetic_plan):
    areas = list_flow_areas(synthetic_plan)
    assert list(areas.index) == ["meshArea"]
    assert areas.index.name == "name"
    row = areas.loc["meshArea"]
    assert row["Cell Count"] == 4
    assert row["faces"] == 14
    assert row["face_points"] == 11
    assert row["File Version"] == "HEC-RAS 6.7 synthetic"
    assert row["Plan Title"] == "synthetic"


def test_list_flow_areas_follows_the_area_name(tmp_path):
    path = testing.write_synthetic_plan(tmp_path / "named.hdf", area="other")
    assert list(list_flow_areas(path).index) == ["other"]


def test_pipe_nodes_reads_names_points_and_attributes(synthetic_plan):
    nodes = pipe_nodes(synthetic_plan)
    assert list(nodes.columns)[:3] == ["Name", "x", "y"]
    assert list(nodes["Name"]) == ["Node 1", "Node 2"]
    assert list(nodes["x"]) == [0.5, 2.5]
    assert list(nodes["y"]) == [0.5, 0.5]
    assert list(nodes["Invert Elevation"]) == [4.0, 4.5]


def test_pipe_nodes_is_empty_without_a_pipe_network(tmp_path):
    path = testing.write_synthetic_plan(tmp_path / "plain.hdf", pipe_nodes=False)
    nodes = pipe_nodes(path)
    assert nodes.empty
    assert list(nodes.columns) == ["Name", "x", "y"]


@pytest.mark.parametrize("kind", ["str", "path", "file"])
@pytest.mark.parametrize("function", [list_flow_areas, open_flow_area, pipe_nodes])
def test_paths_and_open_files_are_accepted(synthetic_plan, kind, function):
    def read(source):
        result = function(source)
        return result.to_dataframe() if isinstance(result, xu.UgridDataset) else result

    expected = read(synthetic_plan)
    if kind == "file":
        with open(synthetic_plan, "rb") as handle:
            result = read(handle)
    else:
        result = read(str(synthetic_plan) if kind == "str" else synthetic_plan)
    pd.testing.assert_frame_equal(result, expected)


# ---- open_flow_area ----------------------------------------------------------------------------


@pytest.fixture
def synthetic_uds(synthetic_plan):
    return open_flow_area(synthetic_plan)


def test_ghost_cells_are_dropped_and_ghost_neighbours_are_minus_one(synthetic_uds):
    uds = synthetic_uds
    assert isinstance(uds, xu.UgridDataset)
    assert uds.grids[0].n_face == 4
    assert uds["Water Surface"].shape == (3, 4)
    cells = uds["Faces Cell Indexes"]
    assert cells.dims == ("mesh2d_nEdges", "two")
    assert (cells.values[3:, 1] == -1).all()
    np.testing.assert_array_equal(cells.values[:3], [[0, 1], [2, 1], [1, 3]])
    assert cells.attrs["comment"] == "indexes of ghost cells (>= Cell Count) written as -1"


def test_hec_ras_face_order_is_the_edge_order(synthetic_uds):
    grid = synthetic_uds.grids[0]
    np.testing.assert_array_equal(grid.edge_node_connectivity, testing.FACE_POINTS)
    np.testing.assert_array_equal(synthetic_uds["Face Flow"].values[0], np.arange(1, 15))


def test_grid_edge_face_connectivity_matches_hec_ras(synthetic_uds):
    np.testing.assert_array_equal(
        synthetic_uds.grids[0].edge_face_connectivity, synthetic_uds["Faces Cell Indexes"].values
    )


def test_attributes_are_verbatim_and_units_is_copied(synthetic_uds):
    attrs = synthetic_uds["Face Flow"].attrs
    assert attrs["Units"] == "cfs"
    assert attrs["units"] == "cfs"
    assert attrs["Location"] == "Faces"
    assert synthetic_uds["Cell Cumulative Precipitation Depth"].attrs["Location"] == "Cell"


def test_singular_location_is_read_on_cells(synthetic_uds):
    da = synthetic_uds["Cell Cumulative Precipitation Depth"]
    assert da.dims == ("time", "mesh2d_nFaces")
    assert da.shape == (3, 4)


def test_arrays_without_location_warn_and_groups_are_skipped(synthetic_plan, recwarn):
    with pytest.warns(UserWarning, match="Courant Number Max"):
        uds = open_flow_area(synthetic_plan)
    assert "Courant Number Max" not in uds
    assert not any("Boundary Conditions" in str(w.message) for w in recwarn.list)


def test_time_comes_from_time_date_stamp_and_days_are_kept(synthetic_uds):
    expected = pd.DatetimeIndex(["2020-01-01 00:00", "2020-01-01 12:00", "2020-01-02 00:00"])
    assert (synthetic_uds["time"].to_index() == expected).all()
    np.testing.assert_array_equal(synthetic_uds["time_days"].values, [0, 0.5, 1])
    assert synthetic_uds["time_days"].attrs == {"Time": "days", "hecras_name": "Time"}
    assert "Time" not in synthetic_uds.variables


def test_parse_time_date_stamp_reads_24_hundred_as_next_midnight():
    result = parse_time_date_stamp([b"01JAN2020 24:00:00"])
    assert result[0] == pd.Timestamp("2020-01-02")


def test_parse_time_date_stamp_reads_a_nul_padded_s19_value():
    values = np.array([b"30NOV2016 00:00:00 "], dtype="S19")
    padded = np.array([b"30NOV2016 00:00:00\x00"], dtype="S19")
    assert parse_time_date_stamp(list(values))[0] == pd.Timestamp("2016-11-30")
    assert parse_time_date_stamp(list(padded))[0] == pd.Timestamp("2016-11-30")


def test_crs_is_read_from_projection_and_can_be_overridden(synthetic_plan, tmp_path):
    assert open_flow_area(synthetic_plan).grids[0].crs.to_epsg() == 2263
    assert open_flow_area(synthetic_plan, crs=32616).grids[0].crs.to_epsg() == 32616
    path = testing.write_synthetic_plan(tmp_path / "noproj.hdf", projection=False)
    with pytest.warns(UserWarning, match="Projection"):
        uds = open_flow_area(path)
    assert uds.grids[0].crs is None


def test_depth_is_derived_and_labelled_when_hydraulic_depth_is_absent(synthetic_plan):
    with pytest.warns(UserWarning):
        uds = open_flow_area(synthetic_plan)
    depth = uds["depth"]
    expected = uds["Water Surface"].values - uds["Cells Minimum Elevation"].values
    np.testing.assert_allclose(depth.values, expected)
    assert depth.attrs["units"] == "ft"
    assert depth.attrs["derivation"] == (
        "Water Surface - Cells Minimum Elevation (ras2xugrid; not a HEC-RAS output)"
    )
    with h5py.File(synthetic_plan, "r+") as file:
        group = file[f"{RESULTS}/2D Flow Areas/meshArea"]
        data = group.create_dataset("Cell Hydraulic Depth", data=np.ones((3, 15), "float32"))
        data.attrs["Units"] = np.bytes_(b"ft")
        data.attrs["Location"] = np.bytes_(b"Cells")
    with pytest.warns(UserWarning):
        uds = open_flow_area(synthetic_plan)
    assert "depth" not in uds
    assert "Cell Hydraulic Depth" in uds


def test_variables_and_time_select(synthetic_plan):
    uds = open_flow_area(synthetic_plan, variables=["Face Flow"])
    assert "Face Flow" in uds
    for name in ["Water Surface", "Face Cumulative Volume", "depth"]:
        assert name not in uds
    assert "Cells Surface Area" in uds
    assert "Cells Minimum Elevation" in uds
    with pytest.warns(UserWarning):
        uds = open_flow_area(synthetic_plan, time=slice("2020-01-01 06:00", None))
    assert uds.sizes["time"] == 2
    assert uds["Water Surface"].shape == (2, 4)
    assert uds["time_days"].shape == (2,)
    with pytest.raises(KeyError, match="Nope.*Face Flow"):
        open_flow_area(synthetic_plan, variables=["Nope"])


def test_every_english_month_abbreviation_parses():
    months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
    result = parse_time_date_stamp([f"15{m}2021 06:30:00".encode() for m in months])
    assert list(result.month) == list(range(1, 13))
    assert (result.day == 15).all()


def test_variables_or_time_without_results_raise(tmp_path):
    path = testing.write_synthetic_plan(tmp_path / "geom.hdf", results=False)
    with pytest.raises(KeyError, match="Time Date Stamp"):
        open_flow_area(path, variables=["Face Flow"])
    with pytest.raises(ValueError, match="Time Date Stamp"):
        open_flow_area(path, time=slice("2020-01-01", None))


def test_variables_without_this_areas_results_raise(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        del file[f"{RESULTS}/2D Flow Areas/meshArea"]
    with pytest.raises(KeyError, match="2D Flow Areas/meshArea"):
        open_flow_area(synthetic_plan, variables=["Face Flow"])
    assert "time" not in open_flow_area(synthetic_plan).dims


def test_a_location_less_array_warns_even_when_not_selected(synthetic_plan):
    with pytest.warns(UserWarning, match="Courant Number Max"):
        open_flow_area(synthetic_plan, variables=["Face Flow"])


def test_time_axes_of_different_lengths_raise(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        del file[f"{RESULTS}/Time"]
        file.create_dataset(f"{RESULTS}/Time", data=np.array([0.0, 0.5]))
    with pytest.raises(ValueError, match=r"(?s)meshArea.*Time Date Stamp: 3.*Time: 2"):
        open_flow_area(synthetic_plan)


def test_a_time_slice_selecting_nothing_raises(synthetic_plan):
    with pytest.raises(ValueError, match=r"(?s)2020-01-01.*2020-01-02"):
        open_flow_area(synthetic_plan, time=slice("2021-01-01", None))


def test_area_must_be_named_when_the_file_has_several(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        file.copy(f"{GEOMETRY}/meshArea", f"{GEOMETRY}/second")
        file.copy(f"{RESULTS}/2D Flow Areas/meshArea", f"{RESULTS}/2D Flow Areas/second")
        old = file[f"{GEOMETRY}/Attributes"][()]
        new = np.concatenate([old, old])
        new["Name"][1] = b"second"
        del file[f"{GEOMETRY}/Attributes"]
        file.create_dataset(f"{GEOMETRY}/Attributes", data=new)
    with pytest.raises(ValueError, match=r"(?s)meshArea.*second"):
        open_flow_area(synthetic_plan)
    with pytest.raises(KeyError, match=r"(?s)meshArea.*second"):
        open_flow_area(synthetic_plan, area="nope")
    with pytest.warns(UserWarning):
        assert open_flow_area(synthetic_plan, area="second").attrs["flow_area"] == "second"


def test_a_plan_without_results_opens_its_mesh(tmp_path):
    path = testing.write_synthetic_plan(tmp_path / "geom.hdf", results=False)
    uds = open_flow_area(path)
    assert "time" not in uds.dims
    assert "Cells Surface Area" in uds
    assert "Faces Cell Indexes" in uds
    assert uds.attrs["flow_area"] == "meshArea"
    assert uds.attrs["Plan Title"] == "synthetic"


# ---- errors and edge cases ---------------------------------------------------------------------


def test_list_flow_areas_has_no_plan_title_without_plan_information(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        del file["Plan Data/Plan Information"]
    assert pd.isna(list_flow_areas(synthetic_plan).loc["meshArea", "Plan Title"])


def test_a_flow_area_without_faces_facepoint_indexes_names_area_and_path(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        del file[f"{GEOMETRY}/meshArea/Faces FacePoint Indexes"]
    with pytest.raises(ValueError, match=r"meshArea.*Faces FacePoint Indexes"):
        list_flow_areas(synthetic_plan)


def test_an_attributes_name_without_a_group_raises_value_error(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        del file[f"{GEOMETRY}/meshArea"]
    with pytest.raises(ValueError, match=r"meshArea.*2D Flow Areas/meshArea"):
        list_flow_areas(synthetic_plan)
    with pytest.raises(ValueError, match=r"meshArea.*2D Flow Areas/meshArea"):
        open_flow_area(synthetic_plan)


def test_pipe_nodes_without_points_raise_value_error(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        del file["Geometry/Pipe Nodes/Points"]
    with pytest.raises(ValueError, match=r"Geometry/Pipe Nodes/Points"):
        pipe_nodes(synthetic_plan)


def test_corrupt_text_is_an_error_not_a_replacement_character():
    from ras2xugrid._hdf import decode

    assert decode(np.bytes_(b"caf\xc3\xa9 ")) == "caf\u00e9"
    with pytest.raises(UnicodeDecodeError):
        decode(b"bad \xff byte")


def test_a_two_d_array_without_location_does_not_set_the_time_length(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        group = file[f"{RESULTS}/2D Flow Areas/meshArea"]
        group.create_dataset("Not Time First", data=np.zeros((7, 2), dtype="float32"))
    with pytest.warns(UserWarning, match="Not Time First"):
        uds = open_flow_area(synthetic_plan)
    assert "Not Time First" not in uds


def test_a_located_array_of_the_wrong_length_still_raises(synthetic_plan):
    with h5py.File(synthetic_plan, "r+") as file:
        group = file[f"{RESULTS}/2D Flow Areas/meshArea"]
        data = group.create_dataset("Short", data=np.zeros((2, 15), dtype="float32"))
        data.attrs["Location"] = np.bytes_(b"Cells")
    with pytest.raises(ValueError, match=r"Short: 2"):
        open_flow_area(synthetic_plan)


def test_an_unknown_month_names_the_stamp():
    with pytest.raises(ValueError, match="15XYZ2021 06:30:00"):
        parse_time_date_stamp([b"15XYZ2021 06:30:00"])


def test_time_and_time_days_survive_zarr_and_netcdf(synthetic_uds, tmp_path):
    # The zarr round trip fails on the old `Time` only on a case-insensitive filesystem (macOS,
    # Windows), where `Time` and `time` are one path; the case-fold assertion guards Linux too.
    source = synthetic_uds.ugrid.to_dataset()
    names = [*source.variables]
    assert len({name.lower() for name in names}) == len(names)
    source.to_zarr(tmp_path / "round.zarr", zarr_format=3, consolidated=False)
    with xr.open_zarr(tmp_path / "round.zarr", consolidated=False) as back:
        assert "time" in back.variables and "time_days" in back.variables
        np.testing.assert_array_equal(back["time_days"].values, [0, 0.5, 1])
        assert back["time_days"].attrs == synthetic_uds["time_days"].attrs

    synthetic_uds.ugrid.to_netcdf(tmp_path / "round.nc")
    with xr.open_dataset(tmp_path / "round.nc") as back:
        assert "time" in back.variables and "time_days" in back.variables
        np.testing.assert_array_equal(back["time_days"].values, [0, 0.5, 1])


def test_a_plan_without_2d_flow_areas_holds_zero_areas(tmp_path):
    path = testing.write_synthetic_plan(tmp_path / "oned.hdf")
    with h5py.File(path, "r+") as file:
        del file[f"{GEOMETRY}/Attributes"]
    with pytest.raises(ValueError, match="holds 0 2D flow areas"):
        open_flow_area(path)
    areas = list_flow_areas(path)
    assert areas.empty
    assert list(areas.columns) == list(
        list_flow_areas(testing.write_synthetic_plan(tmp_path / "ref.hdf")).columns
    )
