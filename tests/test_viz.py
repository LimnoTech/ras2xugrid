"""`mesh_map`: each triangle of a UGRID mesh carries its own cell's value."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

xu = pytest.importorskip("xugrid")
pytest.importorskip("datashader")
hv = pytest.importorskip("holoviews")
xr = pytest.importorskip("xarray")

from ras2xugrid.viz import _cell_trimesh, mesh_map  # noqa: E402


def _mixed_grid(crs: int | None = None) -> xu.Ugrid2d:
    """Two unit squares side by side and a triangle on top of the right one."""
    x = np.array([0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 1.5])
    y = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 2.0])
    faces = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [4, 5, 6, -1]])
    return xu.Ugrid2d(x, y, -1, faces, crs=crs)


def _values_by_pixel(grid: xu.Ugrid2d, values: np.ndarray, **kwargs):
    from holoviews.operation.datashader import rasterize

    trimesh = _cell_trimesh(grid, values, (grid.node_x, grid.node_y))
    image = rasterize(trimesh, aggregator="mean", dynamic=False, width=60, height=60, **kwargs)
    xs = np.asarray(image.dimension_values(0, expanded=False))
    ys = np.asarray(image.dimension_values(1, expanded=False))
    grid_x, grid_y = np.meshgrid(xs, ys)
    pixels = image.dimension_values(2, flat=False)
    return grid_x, grid_y, np.asarray(pixels, dtype=float)


def _check_pixel_rule(grid: xu.Ugrid2d, values: np.ndarray) -> None:
    grid_x, grid_y, pixels = _values_by_pixel(grid, values)
    points = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    cells = np.asarray(grid.locate_points(points)).reshape(pixels.shape)
    inside = cells >= 0
    assert inside.any()
    assert np.all(pixels[inside & ~np.isnan(pixels)] == values[cells[inside & ~np.isnan(pixels)]])
    assert np.mean(~np.isnan(pixels[inside])) >= 0.9


def test_every_pixel_inside_a_cell_has_that_cells_value():
    _check_pixel_rule(_mixed_grid(), np.array([1.0, 2.0, 3.0]))


def test_a_modflow_style_grid_draws():
    grid = xu.Ugrid2d.from_structured_intervals1d(
        np.array([0.0, 1.0, 2.0, 4.0]), np.array([0.0, 1.0, 3.0])
    )
    assert grid.n_face == 6
    _check_pixel_rule(grid, np.arange(1.0, 7.0))


def _time_uda(n: int = 4) -> xu.UgridDataArray:
    grid = _mixed_grid()
    times = pd.date_range("2020-01-01", periods=n, freq="h")
    data = np.arange(n * 3, dtype=float).reshape(n, 3)
    da = xr.DataArray(
        data, dims=("time", grid.face_dimension), coords={"time": times}, name="depth"
    )
    return xu.UgridDataArray(da, grid)


def test_the_slider_covers_every_time_step():
    uda = _time_uda()
    dmap = mesh_map(uda, tiles=None)
    assert isinstance(dmap, hv.DynamicMap)
    kdim = dmap.kdims[0]
    assert kdim.name == "time"
    assert list(pd.to_datetime(kdim.values)) == list(uda["time"].to_index())


def _clim(element) -> tuple[float, float]:
    frame = element[element.kdims[0].values[0]] if isinstance(element, hv.DynamicMap) else element
    found = hv.Store.lookup_options("bokeh", frame, "plot").kwargs.get("clim")
    if found is None:
        found = hv.Store.lookup_options("bokeh", frame, "style").kwargs.get("clim")
    return found


def test_colour_range_is_fixed_across_time():
    uda = _time_uda()
    assert _clim(mesh_map(uda, tiles=None)) == (float(uda.min()), float(uda.max()))
    assert _clim(mesh_map(uda, tiles=None, clim=(-1.0, 5.0))) == (-1.0, 5.0)


def _frames(layer) -> list:
    """The elements one frame of a (possibly dynamic) layer is made of."""
    frame = layer[()] if isinstance(layer, hv.DynamicMap) and not layer.kdims else layer
    return list(frame) if isinstance(frame, hv.Overlay) else [frame]


def test_tiles_only_with_a_crs():
    values = xr.DataArray(np.array([1.0, 2.0, 3.0]), dims=("mesh2d_nFaces",), name="depth")
    with_crs = mesh_map(xu.UgridDataArray(values, _mixed_grid(crs=26916)))
    without = mesh_map(xu.UgridDataArray(values, _mixed_grid()))
    assert any(isinstance(item, hv.Tiles) for item in _frames(with_crs))
    assert not any(isinstance(item, hv.Tiles) for item in _frames(without))


def test_the_displayed_element_is_named_after_the_variable():
    uda = _time_uda()
    uda.attrs["units"] = "m"
    dmap = mesh_map(uda, tiles=None)
    vdim = dmap[dmap.kdims[0].values[0]].vdims[0]
    assert vdim.label == uda.name
    assert vdim.unit == "m"


@pytest.mark.parametrize("name", ["x", "y", "v0", "v1", "v2", "index"])
def test_a_variable_named_like_a_mesh_column_draws(name):
    values = xr.DataArray(np.array([1.0, 2.0, 3.0]), dims=("mesh2d_nFaces",), name=name)
    dmap = mesh_map(xu.UgridDataArray(values, _mixed_grid()), tiles=None)
    assert isinstance(dmap, hv.DynamicMap)
    image = hv.render(dmap)  # raises when the value collides with a mesh column
    assert image is not None
    assert dmap[()].vdims[0].label == name


def test_a_variable_named_x_draws_over_tiles():
    values = xr.DataArray(np.array([1.0, 2.0, 3.0]), dims=("mesh2d_nFaces",), name="x")
    dmap = mesh_map(xu.UgridDataArray(values, _mixed_grid(crs=26916)))
    assert hv.render(dmap, backend="bokeh") is not None
    assert dmap[()].values()[-1].vdims[0].label == "x"


def test_an_unknown_tile_source_lists_the_known_ones():
    values = xr.DataArray(np.array([1.0, 2.0, 3.0]), dims=("mesh2d_nFaces",), name="depth")
    uda = xu.UgridDataArray(values, _mixed_grid(crs=26916))
    with pytest.raises(ValueError, match="CartoLight"):
        mesh_map(uda, tiles="NoSuchTiles")


def test_a_time_frame_holds_that_steps_values():
    uda = _time_uda()
    grid = uda.grid
    dmap = mesh_map(uda, tiles=None)
    for k in (0, 3):
        # index the DynamicMap by time: the public route to one displayed frame
        image = dmap[dmap.kdims[0].values[k]]
        xs = np.asarray(image.dimension_values(0, expanded=False))
        ys = np.asarray(image.dimension_values(1, expanded=False))
        grid_x, grid_y = np.meshgrid(xs, ys)
        pixels = np.asarray(image.dimension_values(2, flat=False), dtype=float)
        cells = np.asarray(grid.locate_points(np.column_stack([grid_x.ravel(), grid_y.ravel()])))
        cells = cells.reshape(pixels.shape)
        hit = (cells >= 0) & ~np.isnan(pixels)
        assert hit.any()
        # datashader's mean sums in float32 where pixels meet, so compare to a tolerance
        assert np.allclose(pixels[hit], uda.values[k][cells[hit]], rtol=1e-5)


def test_all_nan_values_are_refused_naming_the_variable():
    grid = _mixed_grid()
    values = xr.DataArray(np.full(3, np.nan), dims=(grid.face_dimension,), name="depth")
    with pytest.raises(ValueError, match="depth"):
        mesh_map(xu.UgridDataArray(values, grid))


def test_values_on_edges_are_refused():
    grid = _mixed_grid()
    values = xr.DataArray(np.ones(grid.n_edge), dims=(grid.edge_dimension,), name="flux")
    with pytest.raises(TypeError, match=grid.edge_dimension):
        mesh_map(xu.UgridDataArray(values, grid))


def test_an_extra_dimension_is_refused():
    grid = _mixed_grid()
    values = xr.DataArray(np.ones((2, 3)), dims=("layer", grid.face_dimension), name="h")
    with pytest.raises(ValueError, match="layer"):
        mesh_map(xu.UgridDataArray(values, grid))
