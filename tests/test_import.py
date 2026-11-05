"""Smoke test: the package imports and knows its version."""

from __future__ import annotations


def test_package_imports_and_has_a_version():
    import ras2xugrid

    assert isinstance(ras2xugrid.__version__, str)
    assert ras2xugrid.__version__
