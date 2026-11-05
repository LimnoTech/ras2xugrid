"""Draw cell-valued UGRID variables per cell.

HEC-RAS 2D areas (and MODFLOW 6 DISV grids) carry one value per cell. :func:`mesh_map` draws
each cell with its own value: every triangle of the grid's triangulation takes the value of the
cell it came from, and datashader rasterizes the triangles with ``aggregator="mean"``. Averaging
values onto the nodes instead would blend each cell with its neighbours.

This module is part of the optional ``viz`` extra (``pip install 'ras2xugrid[viz]'``). Importing
it loads no plotting library: holoviews, bokeh, datashader and colorcet are imported inside the
functions, so ``import ras2xugrid`` stays light. Use ``from ras2xugrid.viz import mesh_map``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import holoviews as hv
    import numpy as np
    import xugrid as xu

__all__ = ["mesh_map"]


def _viz_missing(error: ImportError) -> ImportError:
    """The error to raise when a plotting package is absent, naming it and the extra."""
    return ImportError(
        f"mesh_map needs the viz extra (missing {error.name or 'a plotting package'!r}): "
        "pip install 'ras2xugrid[viz]'"
    )


_NODE_X, _NODE_Y = "_node_x", "_node_y"
_CELL_VALUE = "_cell_value"  # the value column's own name; a variable's name could be x or v0


def _cell_trimesh(
    grid: xu.Ugrid2d,
    values: np.ndarray,
    xy: tuple[np.ndarray, np.ndarray],
) -> hv.TriMesh:
    """Triangulate a mesh so each triangle carries the value of the cell it came from.

    Drawing node values would blend a cell's neighbours into it; a cell-valued variable (HEC-RAS
    depth, a MODFLOW 6 DISV head) has one value per cell, so every triangle of a polygon cell
    takes that cell's value. ``Ugrid2d.triangulation`` gives
    ``((node_x, node_y, triangles), face_index)``, the index being the cell each triangle
    belongs to. ``xy`` are the node coordinates to draw at (projected or not). The value
    column is named ``_cell_value``, never the variable's own name, which could be ``x`` or
    ``v0`` and collide with the mesh's own columns; :func:`mesh_map` labels it afterwards.
    """
    try:
        import holoviews as hv
    except ImportError as error:
        raise _viz_missing(error) from error
    import numpy as np
    import pandas as pd

    (_, _, triangles), face_index = grid.triangulation
    values = np.asarray(values)
    simplices = pd.DataFrame(
        {
            "v0": triangles[:, 0],
            "v1": triangles[:, 1],
            "v2": triangles[:, 2],
            _CELL_VALUE: values[face_index],
        }
    )
    nodes = pd.DataFrame({_NODE_X: xy[0], _NODE_Y: xy[1], "index": np.arange(len(xy[0]))})
    node_dims = [
        hv.Dimension((_NODE_X, "x coordinate")),
        hv.Dimension((_NODE_Y, "y coordinate")),
        "index",
    ]
    return hv.TriMesh(
        (simplices, hv.Nodes(nodes, node_dims)),
        vdims=[_CELL_VALUE],
    )


def mesh_map(
    uda: xu.UgridDataArray,
    *,
    cmap: Any = None,
    clim: tuple[float, float] | None = None,
    tiles: str | None = "CartoLight",
    alpha: float = 0.8,
    **opts: Any,
) -> hv.DynamicMap:
    """Draw a cell-valued UGRID variable per cell, with a time slider and a basemap.

    Each triangle of the mesh's triangulation carries its own cell's value and is rasterized
    with datashader (``aggregator="mean"``), so a pixel lying inside one cell shows that cell's
    value exactly. The map re-rasterizes as you zoom; where cells are smaller than a pixel at the
    current zoom the pixel shows their mean. HEC-RAS 2D areas and MODFLOW 6 DISV grids both draw
    this way; cell values are not averaged onto nodes, which would blend neighbouring cells.

    ``uda`` must be on the grid's faces (``TypeError`` naming the dimension found otherwise),
    and may have a ``time`` dimension (any other extra dimension raises ``ValueError``). The
    default ``cmap`` is ``colorcet.cm["rainbow4"]``; the default ``clim`` is the ``nanmin`` and
    ``nanmax`` over **all** time steps, so colours mean the same on every frame (the values are
    loaded into memory to compute it; an all-NaN array raises ``ValueError``). With a CRS the
    nodes are projected once to EPSG:3857 and drawn over ``tiles``, a name from
    ``holoviews.element.tiles.tile_sources``; without one, or with ``tiles=None``, there is no
    basemap; an unknown name raises ``ValueError`` listing the known ones. ``alpha`` applies
    over the basemap; it is 1.0 without tiles. Extra ``opts`` go to the image's ``.opts``.

    Returns a ``DynamicMap`` keyed on ``time`` when ``uda`` has it (every step an explicit
    value). Without a ``time`` dimension it is a single-frame ``DynamicMap`` with no key, not a
    bare element, because the rasterization is redone on every zoom. With a basemap the frame
    is an ``Overlay`` of the tiles and the image.
    """
    try:
        import colorcet
        import datashader  # noqa: F401  # rasterize needs it; fail here, not at first draw
        import holoviews as hv
        import holoviews.plotting.bokeh  # noqa: F401  # registers the options `.opts` validates
        from holoviews.operation.datashader import rasterize
    except ImportError as error:
        raise _viz_missing(error) from error
    import numpy as np
    import xugrid as xu

    tile_sources = hv.element.tiles.tile_sources
    if tiles is not None and tiles not in tile_sources:
        raise ValueError(f"mesh_map: unknown tiles {tiles!r}; choose from {sorted(tile_sources)}")
    grid = uda.grid
    if not isinstance(grid, xu.Ugrid2d):
        raise TypeError(f"mesh_map draws a 2D mesh (Ugrid2d), not {type(grid).__name__}")
    face_dim = grid.face_dimension
    other = [dim for dim in uda.dims if dim not in (face_dim, "time")]
    if face_dim not in uda.dims:
        raise TypeError(
            f"mesh_map draws values on the grid's faces ({face_dim!r}); "
            f"this array has dimensions {tuple(uda.dims)}"
        )
    if other:
        raise ValueError(
            f"mesh_map draws dimensions {face_dim!r} and 'time' only; "
            f"select or reduce {other} first"
        )

    name = str(uda.name) if uda.name is not None else "value"
    data = uda.obj.transpose(..., face_dim)
    cmap = colorcet.cm["rainbow4"] if cmap is None else cmap
    if clim is None:
        if not np.isfinite(data.values).any():
            raise ValueError(f"mesh_map: {name!r} has no finite values to draw")
        clim = (float(np.nanmin(data.values)), float(np.nanmax(data.values)))

    x, y = grid.node_x, grid.node_y
    crs = grid.crs
    with_tiles = tiles is not None and crs is not None
    if with_tiles:
        from pyproj import Transformer

        x, y = Transformer.from_crs(crs, 3857, always_xy=True).transform(x, y)
    x, y = np.asarray(x), np.asarray(y)

    vdim = hv.Dimension((_CELL_VALUE, name), unit=uda.attrs.get("units"))
    if "time" in data.dims:
        times = list(data["time"].values)
        steps = {t: i for i, t in enumerate(times)}

        def draw(time):
            return _cell_trimesh(grid, data.isel(time=steps[time]).values, (x, y))

        meshes: Any = hv.DynamicMap(draw, kdims=[hv.Dimension("time", values=times)])
    else:
        meshes = _cell_trimesh(grid, data.values, (x, y))

    # dynamic rasterization re-aggregates at the current zoom and pixel size
    layer = rasterize(meshes, aggregator="mean", vdim_prefix="")
    layer = layer.redim(**{_CELL_VALUE: vdim})
    layer = layer.opts(cmap=cmap, clim=clim, colorbar=True, alpha=alpha if with_tiles else 1.0)
    if opts:
        layer = layer.opts(**opts)
    if with_tiles:
        return tile_sources[tiles]() * layer
    return layer
