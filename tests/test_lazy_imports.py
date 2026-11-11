"""Importing ras2xugrid never loads a plotting library; `mesh_map` names
the extra when absent."""

from __future__ import annotations

import subprocess
import sys

import pytest

PLOTTING = ("holoviews", "bokeh", "datashader", "colorcet")


@pytest.mark.parametrize("module", ["ras2xugrid", "ras2xugrid.viz"])
def test_importing_loads_no_plotting_library(module):
    code = f"import sys, {module}; print([m for m in {PLOTTING!r} if m in sys.modules])"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


BLOCK = (
    "import sys\n"
    "class Block:\n"
    "    def find_spec(self, name, *args):\n"
    "        if name.split('.')[0] == {blocked!r}:\n"
    "            raise ImportError('blocked', name={blocked!r})\n"
    "sys.meta_path.insert(0, Block())\n"
    "from ras2xugrid.viz import mesh_map\n"
    "mesh_map(None)\n"
)


@pytest.mark.parametrize("blocked", PLOTTING)
def test_mesh_map_without_a_viz_package_names_it_and_the_extra(blocked):
    code = BLOCK.format(blocked=blocked)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode != 0
    assert "ras2xugrid[viz]" in out.stderr
    assert repr(blocked) in out.stderr
