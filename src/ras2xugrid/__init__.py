"""Read HEC-RAS 2D plan files into xugrid."""

from __future__ import annotations

try:
    from ._version import __version__
except ImportError:  # pragma: no cover
    # - a source tree that was never built or installed
    __version__ = "0.0.0"

from .plan import list_flow_areas, open_flow_area, pipe_nodes
from .sections import (
    boundary_faces,
    cross_section_faces,
    cross_section_series,
    faces_from_table,
)

__all__: list[str] = [
    "list_flow_areas",
    "open_flow_area",
    "pipe_nodes",
    "boundary_faces",
    "faces_from_table",
    "cross_section_faces",
    "cross_section_series",
]
