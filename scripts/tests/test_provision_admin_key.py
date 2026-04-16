"""Tests for scripts/ci/provision_admin_key.py — admin scope provisioning."""

from __future__ import annotations

import ast
import os


def test_create_key_includes_admin_scope():
    """Provisioned key must pass scopes containing 'admin' to create_key().

    This is a source-level assertion: we parse the script's AST and verify
    that the create_key() call includes scopes=['read', 'write', 'admin'].
    Without admin scope the key defaults to ['read', 'write'] and will NOT
    bypass budget caps or ownership checks — causing 402 in smoke tests.
    """
    script_path = os.path.join(os.path.dirname(__file__), "..", "ci", "provision_admin_key.py")
    source = open(script_path).read()
    tree = ast.parse(source)

    # Walk AST to find km.create_key(...) call
    found_create_key = False
    has_admin_scope = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match: km.create_key(...) or *.create_key(...)
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "create_key":
            found_create_key = True
            # Check keyword arguments for scopes=
            for kw in node.keywords:
                if kw.arg == "scopes":
                    if isinstance(kw.value, ast.List):
                        scope_values = [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)]
                        if "admin" in scope_values:
                            has_admin_scope = True

    assert found_create_key, "create_key() call not found in provision_admin_key.py"
    assert has_admin_scope, (
        "create_key() must include scopes=['read', 'write', 'admin']. "
        "Without 'admin' scope, the key won't bypass budget caps (HTTP 402)."
    )
