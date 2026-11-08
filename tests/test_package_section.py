"""Hold ``[tool.pixi.package]`` to the lists it repeats, and the pins around it.

ras2xugrid is a pixi-build source package: a consumer that names it under a conda
``[dependencies]`` table gets its ``run-dependencies`` and ``run-constraints`` in its own solve.
Those tables repeat ``[project.dependencies]`` and the viz floors in conda names, so these tests
keep them in step, as ``test_dependency_parity.py`` does for the pixi features.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import test_dependency_parity
import yaml
from test_dependency_parity import (
    CONDA_ONLY,
    PYPI_ONLY,
    conda_specifier,
    normalize,
    requirement_name,
    requirement_specifier,
)

import ras2xugrid

REPO = Path(__file__).resolve().parents[1]

# The parity module's fixture, shared rather than copied.
pyproject = test_dependency_parity.pyproject

# Today's viz floors (2026-11-06), written out so a change to them is a visible decision.
VIZ_FLOORS = {
    "colorcet": ">=3.2.1",
    "holoviews": ">=1.23",
}


def package(pyproject: dict) -> dict:
    return pyproject["tool"]["pixi"]["package"]


def spec(text: str) -> str:
    """A version specifier with its spaces removed, for comparing conda and PEP 508 text."""
    return re.sub(r"\s+", "", text)


def test_run_dependencies_match_project_dependencies(pyproject):
    """Someone adds a core dependency and forgets the package section (or the reverse)."""
    run_dependencies = package(pyproject)["run-dependencies"]
    conda = {
        normalize(name): conda_specifier(value)
        for name, value in run_dependencies.items()
        if name not in CONDA_ONLY
    }
    pypi = {
        normalize(requirement_name(r)): requirement_specifier(r)
        for r in pyproject["project"]["dependencies"]
        if normalize(requirement_name(r)) not in PYPI_ONLY
    }
    assert sorted(conda.keys() - pypi.keys()) == [], "in run-dependencies, not [project]"
    assert sorted(pypi.keys() - conda.keys()) == [], "in [project], not run-dependencies"
    disagree = {
        name: (pypi[name] or "(none)", conda[name] or "(none)")
        for name in pypi
        if spec(pypi[name]) != spec(conda[name])
    }
    assert not disagree, f"version specifiers differ (PyPI, conda): {disagree}"


def test_run_constraints_are_the_versioned_viz_floors(pyproject):
    """A viz floor that is not a run-constraint never reaches a consumer."""
    viz = pyproject["tool"]["pixi"]["feature"]["viz"]["dependencies"]
    versioned = {name: conda_specifier(value) for name, value in viz.items()}
    versioned = {name: value for name, value in versioned.items() if value}
    run_constraints = {
        name: conda_specifier(value)
        for name, value in package(pyproject)["run-constraints"].items()
    }
    assert run_constraints == versioned
    assert run_constraints == VIZ_FLOORS
    extra = {
        normalize(requirement_name(r)): requirement_specifier(r)
        for r in pyproject["project"]["optional-dependencies"]["viz"]
    }
    disagree = {
        name: (extra.get(name), value)
        for name, value in run_constraints.items()
        if spec(extra.get(name, "")) != spec(value)
    }
    assert not disagree, f"run-constraints differ from the viz extra (extra, conda): {disagree}"


def test_core_feature_holds_only_python(pyproject):
    """The core list lives in run-dependencies; test_dependency_parity.py skips feature.core."""
    assert set(pyproject["tool"]["pixi"]["feature"]["core"]["dependencies"]) == {"python"}


def test_package_python_matches_requires_python(pyproject):
    python = package(pyproject)["run-dependencies"]["python"]
    assert spec(python) == spec(pyproject["project"]["requires-python"])


def test_package_version_is_the_latest_release(pyproject):
    """The package version is the newest released CHANGELOG heading, bumped at each release.

    ``__version__`` still comes from hatch-vcs (``_version.py``), never from this field.
    """
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.findall(r"^## \[?(\d+(?:\.\d+)*)\]?", changelog, flags=re.MULTILINE)
    assert released, "CHANGELOG.md has no released '## x.y.z' heading"
    assert package(pyproject)["version"] == released[0]

    assert pyproject["tool"]["hatch"]["version"]["source"] == "vcs"
    assert "version" in pyproject["project"]["dynamic"]
    from ras2xugrid import _version

    assert ras2xugrid.__version__ == _version.__version__


def test_ci_environment_has_no_jupyter_stack():
    """The self-package brings in only run-dependencies, never the Jupyter stack.

    The ci environment does hold the viz stack (its own feature), so only Jupyter is checked.
    """
    pixi = shutil.which("pixi")
    if pixi is None:
        pytest.skip("pixi is not on PATH")
    listed = subprocess.run(
        [pixi, "list", "--environment", "ci", "--frozen", "--json"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    names = {entry["name"] for entry in json.loads(listed.stdout)}
    assert "ras2xugrid" in names
    present = names & {"jupyterlab", "jupytext", "hvplot"}
    assert not present, f"the ci environment has Jupyter or examples packages: {sorted(present)}"


def satisfies(version: str, specifier: str) -> bool:
    """Whether a dotted version meets a comma-joined ``>=``/``<``/``==`` specifier.

    Raises ValueError naming the text for a version that is not dotted numbers (``latest``) or
    an operator this does not read (``~=``, ``!=``).
    """

    def parts(text: str) -> tuple[int, ...]:
        if not re.fullmatch(r"v?\d+(\.\d+)*", text):
            raise ValueError(f"not a dotted numeric version: {text!r}")
        return tuple(int(p) for p in text.lstrip("v").split("."))

    compare = {
        ">=": lambda a, b: a >= b,
        ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a[: len(b)] == b,
    }
    for clause in spec(specifier).split(","):
        match = re.fullmatch(r"(>=|<=|==|>|<)([^<>=!~]+)", clause)
        if match is None:
            raise ValueError(f"unsupported specifier {clause!r} in {specifier!r}")
        op, bound = match.groups()
        if not compare[op](parts(version), parts(bound)):
            return False
    return True


def test_satisfies_reads_requires_pixi_ranges():
    assert satisfies("v0.76.0", ">=0.76,<0.77")
    assert not satisfies("v0.77.0", ">=0.76,<0.77")
    assert not satisfies("0.75.2", ">=0.76")


def test_satisfies_names_a_version_it_cannot_read():
    with pytest.raises(ValueError, match="'latest'"):
        satisfies("latest", ">=0.76")


@pytest.mark.parametrize("specifier", ["~=0.76", "!=0.77", ">=0.76,!=0.76.1"])
def test_satisfies_refuses_an_unsupported_specifier(specifier):
    with pytest.raises(ValueError, match="unsupported specifier"):
        satisfies("0.76.0", specifier)


def setup_pixi_steps(workflow: dict) -> list[dict]:
    """The prefix-dev/setup-pixi steps of a parsed workflow."""
    return [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps") or []
        if str(step.get("uses", "")).startswith("prefix-dev/setup-pixi")
    ]


def pixi_pin_problems(workflow: dict, required: str | None) -> list[str]:
    """What is wrong with the workflow's pixi pins, one message per step; empty if nothing."""
    problems = []
    for step in setup_pixi_steps(workflow):
        name = step.get("name", step["uses"])
        version = (step.get("with") or {}).get("pixi-version")
        if version is None:
            problems.append(f"{name!r} sets no pixi-version")
        elif required:
            try:
                inside = satisfies(str(version), required)
            except ValueError as error:
                problems.append(f"{name!r}: pixi-version {version!r}: {error}")
            else:
                if not inside:
                    problems.append(f"{name!r}: pixi-version {version!r} is outside {required!r}")
    return problems


def workflow_with(step_with: object) -> dict:
    return {
        "jobs": {
            "j": {
                "steps": [
                    {"name": "Setup pixi", "uses": "prefix-dev/setup-pixi@v0", "with": step_with}
                ]
            }
        }
    }


def test_an_empty_with_is_reported_not_raised():
    assert pixi_pin_problems(workflow_with(None), ">=0.76,<0.77") == [
        "'Setup pixi' sets no pixi-version"
    ]


def test_a_non_numeric_pixi_version_is_reported_with_its_step():
    (problem,) = pixi_pin_problems(workflow_with({"pixi-version": "latest"}), ">=0.76,<0.77")
    assert problem.startswith("'Setup pixi': pixi-version 'latest'")


def test_an_unsupported_requires_pixi_is_reported():
    (problem,) = pixi_pin_problems(workflow_with({"pixi-version": "v0.76.0"}), "~=0.76")
    assert "unsupported specifier" in problem


def test_ci_pins_the_pixi_version(pyproject):
    """pixi-build is a preview, so CI runs the pixi the lock was made with."""
    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yaml").read_text(encoding="utf-8"))
    assert setup_pixi_steps(workflow), "no setup-pixi step found in ci.yaml"
    required = pyproject["tool"]["pixi"]["workspace"].get("requires-pixi")
    problems = pixi_pin_problems(workflow, required)
    assert not problems, "; ".join(problems)
