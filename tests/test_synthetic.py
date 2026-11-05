"""The synthetic plan is written with HEC-RAS's own paths."""

from __future__ import annotations

import h5py
import numpy as np

from ras2xugrid import testing
from ras2xugrid._hdf import GEOMETRY, RESULTS


def test_synthetic_plan_uses_hec_ras_paths(synthetic_plan):
    with h5py.File(synthetic_plan) as file:
        area = file[f"{GEOMETRY}/meshArea"]
        assert area["Cells FacePoint Indexes"].shape == (15, 8)
        np.testing.assert_array_equal(area["Faces Cell Indexes"][()], testing.FACE_CELLS)
        assert file[f"{RESULTS}/2D Flow Areas/meshArea/Face Flow"].shape == (3, 14)


def test_synthetic_plan_fixes_the_rest_of_the_layout(synthetic_plan):
    with h5py.File(synthetic_plan) as file:
        assert file.attrs["File Type"] == b"HEC-RAS Results"
        assert file.attrs["File Version"] == b"HEC-RAS 6.7 synthetic"
        assert file.attrs["Units System"] == b"US Customary"
        assert b"NAD_1983" in file.attrs["Projection"]
        assert file["Plan Data/Plan Information"].attrs["Plan Title"] == b"synthetic"

        area = file[f"{GEOMETRY}/meshArea"]
        indexes = area["Cells FacePoint Indexes"][()]
        for k in range(3, 14):  # ghost row k + 1: its face's two face points, then -1
            np.testing.assert_array_equal(indexes[k + 1, :2], testing.FACE_POINTS[k])
            assert (indexes[k + 1, 2:] == -1).all()
        surface = area["Cells Surface Area"][()]
        elevation = area["Cells Minimum Elevation"][()]
        np.testing.assert_array_equal(surface[:4], [1, 1, 1, 1.25])
        assert (surface[4:] == 0).all()
        np.testing.assert_array_equal(elevation[:4], [5, 5, 5, 6])
        assert np.isnan(elevation[4:]).all()

        series = file[RESULTS]
        np.testing.assert_array_equal(series["Time"][()], [0.0, 0.5, 1.0])
        assert series["Time"].attrs["Time"] == b"days"
        stamps = series["Time Date Stamp"]
        assert stamps.dtype == np.dtype("S18")
        assert list(stamps[()]) == [
            b"01JAN2020 00:00:00",
            b"01JAN2020 12:00:00",
            b"02JAN2020 00:00:00",
        ]

        results = series["2D Flow Areas/meshArea"]
        expected = {
            "Water Surface": (b"ft", b"Cells"),
            "Cell Cumulative Precipitation Depth": (b"in", b"Cell"),
            "Face Flow": (b"cfs", b"Faces"),
            "Face Cumulative Volume": (b"ft^3", b"Faces"),
        }
        for key, (units, location) in expected.items():
            assert results[key].attrs["Units"] == units
            assert results[key].attrs["Location"] == location
        assert results["Courant Number Max"].attrs["Units"] == b"-"
        assert "Location" not in results["Courant Number Max"].attrs
        assert isinstance(results["Boundary Conditions"], h5py.Group)
        assert len(results["Boundary Conditions"]) == 0
