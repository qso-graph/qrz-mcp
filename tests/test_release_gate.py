"""The release gate's own precondition.

`publish.yml` runs `tests/test_security.py` after `pip install pytest pip-audit`
— the package itself is **not** installed, deliberately: those checks read the
source tree rather than import it, so they hold whatever the environment has.
`ci.yml` meanwhile runs `pytest tests --ignore=tests/test_security.py`.

Between them, `test_security.py` executes in exactly one place, and it is the
one where `import qrz_mcp` raises. `ci.yml` here *does* run that file, but
with the package installed — so a test
that imports `qrz_mcp` passes CI and fails the publish, which is the trap.

It is not hypothetical. On 2026-10-12 two such tests were added to solar-mcp's
copy of this file by the same certifi change as #31. Every suite was green and
its 0.3.0 publish run failed at the gate with `ModuleNotFoundError`, publishing
nothing. This file is here so qrz-mcp cannot repeat it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

GATE = Path(__file__).parent / "test_security.py"
PACKAGE = "qrz_mcp"


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_gate_suite_does_not_import_the_package():
    """SOLAR-GATE-001: it must pass with nothing but pytest installed.

    Imports anywhere count, including inside a function body: the gate fails on
    the import whether it is at the top of the file or three frames down.
    """
    tree = ast.parse(GATE.read_text(), filename=str(GATE))
    offenders = sorted(n for n in _imported_names(tree)
                       if n == PACKAGE or n.startswith(f"{PACKAGE}."))
    assert not offenders, (
        f"{GATE.name} imports {offenders}; the release gate runs it with "
        f"{PACKAGE} not installed, so this fails the publish and nothing else"
    )


def test_the_gate_suite_only_needs_the_standard_library_and_pytest():
    """SOLAR-GATE-002: the same trap, one step wider.

    `certifi` was imported here too, and it happens to be installed in CI and
    locally. The gate installs `pytest` and `pip-audit` and nothing else.
    """
    # The real standard-library set rather than a hand-written list: a list I
    # have to remember to extend is the same shape of mistake as the one this
    # file exists to catch. (`sys.stdlib_module_names` is 3.10+, and this
    # package requires 3.11.)
    allowed = set(sys.stdlib_module_names) | {"pytest"}
    tree = ast.parse(GATE.read_text(), filename=str(GATE))
    outside = sorted(n for n in _imported_names(tree) if n.split(".")[0] not in allowed)
    assert not outside, (
        f"{GATE.name} imports {outside}, which the release gate does not install"
    )
