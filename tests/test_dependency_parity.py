"""Guard the dual-declaration invariant between the PyPI and conda dependency lists.

``ras2xugrid`` declares its runtime dependencies twice, on purpose:

* ``[project.dependencies]`` states the contract in PyPI names, so the wheel is
  honest and downstream repositories can consume it as a git dependency.
* ``[tool.pixi.feature.*.dependencies]`` supplies the actual environment from
  conda-forge, including packages with no usable PyPI distribution. The core list is
  ``[tool.pixi.package.run-dependencies]``: this repository consumes itself as a pixi-build
  source package, so ``feature.core`` holds only the environment's python.

Pixi resolves conda first and maps those packages onto their PyPI names, so the
two never fight at install time -- but nothing stops them drifting apart in the
manifest. These tests are what stops that.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"

# Conda packages we depend on that have no counterpart in [project.dependencies].
CONDA_ONLY = {
    "sqlite",  # conda-only: a system library floor, not a Python import; see pyproject.toml
    "python",  # the interpreter itself, not a dependency
    "nodejs",  # JupyterLab build tooling, not a Python import
}

# PyPI requirements with no conda counterpart: none yet.
PYPI_ONLY: set[str] = set()

# Conda spellings that differ from the PyPI name of the same package: none yet.
CONDA_TO_PYPI: dict[str, str] = {}

# The package's run-dependencies, which mirror [project.dependencies] in place of feature.core.
RUN_DEPENDENCIES = "package.run-dependencies"

# Which pixi conda list mirrors which dependency list. The run-dependencies mirror
# [project.dependencies]; ``jupyter`` and ``viz`` map to the extras of the same names. ``core``
# holds only the environment's python. ``dev`` and ``examples`` are deliberately left out:
# ``dev`` is tooling and ``examples`` is notebook-only (what the example imports beyond core,
# viz and jupyter), so neither is a runtime dependency of ras2xugrid and neither has an extra.
FEATURE_TO_EXTRA = {RUN_DEPENDENCIES: None, "jupyter": "jupyter", "viz": "viz"}


def normalize(name: str) -> str:
    """Map a conda spelling onto its PyPI name, then normalize per PEP 503."""
    name = CONDA_TO_PYPI.get(name, name)
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str:
    """Strip version specifiers, extras, and markers from a PEP 508 requirement."""
    return re.split(r"[<>=!~\[;\s]", requirement, maxsplit=1)[0]


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def pypi_names(pyproject: dict, extra: str | None) -> set[str]:
    """Normalized PyPI names for [project.dependencies] or one extra."""
    if extra is None:
        requirements = pyproject["project"]["dependencies"]
    else:
        requirements = pyproject["project"]["optional-dependencies"][extra]
    return {normalize(requirement_name(r)) for r in requirements}


def conda_table(pyproject: dict, feature: str) -> dict:
    """The conda dependency table of one pixi feature, or of the package's run-dependencies."""
    pixi = pyproject["tool"]["pixi"]
    if feature == RUN_DEPENDENCIES:
        return pixi["package"]["run-dependencies"]
    return pixi["feature"][feature]["dependencies"]


def conda_names(pyproject: dict, feature: str) -> set[str]:
    """Raw (unnormalized) conda names declared for one pixi feature."""
    return set(conda_table(pyproject, feature))


def requirement_specifier(requirement: str) -> str:
    """The version part of a PEP 508 requirement, or "" when it is unconstrained."""
    without_name = requirement[len(requirement_name(requirement)) :]
    without_extras = re.sub(r"^\s*\[[^\]]*\]", "", without_name)
    return without_extras.split(";", maxsplit=1)[0].strip()


def conda_specifier(spec: object) -> str:
    """The version part of a pixi conda spec, or "" when it is unconstrained.

    A spec is either a bare string (``"*"``, ``">=3"``) or a table carrying a ``version`` key.
    """
    if isinstance(spec, dict):
        spec = spec.get("version", "*")
    text = str(spec).strip()
    return "" if text == "*" else text


@pytest.mark.parametrize(("feature", "extra"), sorted(FEATURE_TO_EXTRA.items()))
def test_every_pypi_dependency_has_a_conda_counterpart(pyproject, feature, extra):
    """A wheel requirement with no conda package would not install under pixi."""
    declared = pypi_names(pyproject, extra)
    available = {normalize(name) for name in conda_names(pyproject, feature)}
    missing = declared - available - PYPI_ONLY
    assert not missing, (
        f"declared in [project] but absent from the '{feature}' "
        f"conda list (a pixi feature or the package's run-dependencies): {sorted(missing)}"
    )


@pytest.mark.parametrize(("feature", "extra"), sorted(FEATURE_TO_EXTRA.items()))
def test_every_conda_dependency_is_declared_or_allowlisted(pyproject, feature, extra):
    """A conda package absent from [project] makes the wheel metadata a lie."""
    declared = pypi_names(pyproject, extra)
    undeclared = {
        name
        for name in conda_names(pyproject, feature)
        if name not in CONDA_ONLY and normalize(name) not in declared
    }
    assert not undeclared, (
        f"in the '{feature}' conda list (a pixi feature or the package's run-dependencies) but not "
        f"in [project]: {sorted(undeclared)}. "
        "Either declare them, or add them to CONDA_ONLY with a comment saying why."
    )


@pytest.mark.parametrize(("feature", "extra"), sorted(FEATURE_TO_EXTRA.items()))
def test_version_constraints_are_declared_on_both_sides(pyproject, feature, extra):
    """A floor pinned in only one half makes the other half's promise wrong.

    The two tests above compare *names* and stop there, so ``colorcet = ">=3.2.1,<4"`` in the
    pixi feature beside a bare ``"colorcet"`` in the extra passes them both -- and the wheel
    then claims to work with a version the environment forbids. This does not compare specifier
    *syntax*, which legitimately differs between conda and PEP 508; it asserts only that a
    package constrained on one side is constrained on the other, which is where the drift that
    matters shows up.
    """
    if extra is None:
        requirements = pyproject["project"]["dependencies"]
    else:
        requirements = pyproject["project"]["optional-dependencies"][extra]
    pypi_specifiers = {
        normalize(requirement_name(r)): requirement_specifier(r) for r in requirements
    }
    conda_specifiers = {
        normalize(name): conda_specifier(spec)
        for name, spec in conda_table(pyproject, feature).items()
    }

    lopsided = {
        name: (pypi_specifiers[name] or "(none)", conda_specifiers[name] or "(none)")
        for name in pypi_specifiers.keys() & conda_specifiers.keys()
        if bool(pypi_specifiers[name]) != bool(conda_specifiers[name])
    }
    assert not lopsided, (
        f"the '{feature}' conda list and its [project] list disagree on whether a package is "
        f"version-"
        f"constrained (PyPI, conda): {lopsided}. Constrain both halves or neither."
    )


def test_allowlists_contain_no_dead_entries(pyproject):
    """Stop the allowlists rotting into a place where exceptions hide forever."""
    all_conda = conda_names(pyproject, RUN_DEPENDENCIES)
    for feature in pyproject["tool"]["pixi"]["feature"]:
        all_conda |= conda_names(pyproject, feature)

    dead_conda_only = CONDA_ONLY - all_conda
    assert not dead_conda_only, (
        f"CONDA_ONLY lists packages no conda list (a pixi feature or the "
        f"package's run-dependencies) depends on: {sorted(dead_conda_only)}"
    )

    all_pypi = set(pypi_names(pyproject, None))
    for extra in pyproject["project"]["optional-dependencies"]:
        all_pypi |= pypi_names(pyproject, extra)
    dead_pypi_only = PYPI_ONLY - all_pypi
    assert not dead_pypi_only, (
        f"PYPI_ONLY lists packages no extra requires: {sorted(dead_pypi_only)}"
    )

    dead_mappings = set(CONDA_TO_PYPI) - all_conda
    assert not dead_mappings, (
        f"CONDA_TO_PYPI maps packages no conda list (a pixi feature or the "
        f"package's run-dependencies) depends on: {sorted(dead_mappings)}"
    )


def test_feature_to_extra_map_is_complete(pyproject):
    """FEATURE_TO_EXTRA is hand-maintained, unlike CONDA_ONLY and CONDA_TO_PYPI above --
    nothing forced it to stay in step with pyproject.toml. A new
    ``[tool.pixi.feature.*.dependencies]`` table or a new
    ``[project.optional-dependencies]`` extra would otherwise go unparametrized above and
    silently stop being checked. This asserts completeness in both directions.
    """
    all_features = set(pyproject["tool"]["pixi"]["feature"])
    covered_or_excluded = set(FEATURE_TO_EXTRA) | {"dev", "examples", "core"}
    uncovered_features = all_features - covered_or_excluded
    assert not uncovered_features, (
        f"pixi features missing from FEATURE_TO_EXTRA (and not the deliberately-excluded "
        f"'dev', 'examples' and 'core'): {sorted(uncovered_features)}"
    )

    all_extras = set(pyproject["project"]["optional-dependencies"])
    mapped_extras = {extra for extra in FEATURE_TO_EXTRA.values() if extra is not None}
    unmapped_extras = all_extras - mapped_extras
    assert not unmapped_extras, (
        f"[project.optional-dependencies] extras missing from FEATURE_TO_EXTRA: "
        f"{sorted(unmapped_extras)}"
    )
