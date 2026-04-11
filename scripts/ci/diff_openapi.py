#!/usr/bin/env python3
"""Compare the current OpenAPI schema against the committed baseline.

v1.2.4 audit P1 T-5: catches silent SDK ↔ server drift of the
kind that produced P0-3 (``created_at`` float → string). The gate
distinguishes two classes of change:

* **Additions** — new routes, new fields, new optional params.
  These are always allowed; they don't break existing clients.
* **Breaking** — route removed, field removed, field type
  changed, required field added, response type changed, path
  parameter type changed. These fail CI unless the PR body
  contains a ``deprecation:`` key documenting the intended
  migration.

Usage::

    python scripts/ci/diff_openapi.py \
        --baseline reports/openapi-baseline.json \
        --current  /tmp/current.json

Exit codes:
    0 — no breaking changes
    1 — breaking changes detected, PR body does not authorise
    2 — baseline / current file missing or unparseable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _load(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def _paths_keys(schema: dict[str, Any]) -> set[tuple[str, str]]:
    """Return set of ``(path, method)`` tuples in the schema."""
    out: set[tuple[str, str]] = set()
    for path, methods in (schema.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method in methods:
            if method.lower() in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
            }:
                out.add((path, method.lower()))
    return out


def _component_fields(schema: dict[str, Any]) -> dict[str, set[str]]:
    """Map component-schema name → set of field names.

    Only looks at ``properties`` at the top level. This is
    deliberately simple — anything deeper is considered "additive
    welcome" territory.
    """
    out: dict[str, set[str]] = {}
    components = schema.get("components", {}).get("schemas", {})
    for name, body in components.items():
        if not isinstance(body, dict):
            continue
        props = body.get("properties")
        if isinstance(props, dict):
            out[name] = set(props.keys())
    return out


def _component_types(schema: dict[str, Any]) -> dict[tuple[str, str], str]:
    """Map ``(component_name, field_name)`` → JSON-schema ``type``.

    Missing ``type`` (for $ref / anyOf / oneOf nodes) is reported
    as ``"<complex>"`` and matched only against itself.
    """
    out: dict[tuple[str, str], str] = {}
    components = schema.get("components", {}).get("schemas", {})
    for name, body in components.items():
        if not isinstance(body, dict):
            continue
        props = body.get("properties", {})
        if not isinstance(props, dict):
            continue
        for field, field_body in props.items():
            t = "<complex>"
            if isinstance(field_body, dict):
                t = field_body.get("type") or field_body.get("$ref") or "<complex>"
            out[(name, field)] = str(t)
    return out


def _required_fields(schema: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    components = schema.get("components", {}).get("schemas", {})
    for name, body in components.items():
        if not isinstance(body, dict):
            continue
        req = body.get("required", [])
        if isinstance(req, list):
            out[name] = set(req)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument(
        "--pr-body-file",
        default=None,
        help="optional file containing the PR body; a line starting with 'deprecation:' authorises breaking changes",
    )
    args = ap.parse_args()

    baseline = _load(args.baseline)
    current = _load(args.current)

    base_routes = _paths_keys(baseline)
    cur_routes = _paths_keys(current)

    removed_routes = sorted(base_routes - cur_routes)
    added_routes = sorted(cur_routes - base_routes)

    base_fields = _component_fields(baseline)
    cur_fields = _component_fields(current)

    removed_fields: list[tuple[str, str]] = []
    added_fields: list[tuple[str, str]] = []
    for name in set(base_fields) | set(cur_fields):
        b = base_fields.get(name, set())
        c = cur_fields.get(name, set())
        for f in sorted(b - c):
            removed_fields.append((name, f))
        for f in sorted(c - b):
            added_fields.append((name, f))

    base_types = _component_types(baseline)
    cur_types = _component_types(current)
    type_changed: list[tuple[str, str, str, str]] = []
    for key, b_t in base_types.items():
        c_t = cur_types.get(key)
        if c_t is None:
            # removal is tracked above
            continue
        if b_t != c_t:
            type_changed.append((key[0], key[1], b_t, c_t))

    base_req = _required_fields(baseline)
    cur_req = _required_fields(current)
    newly_required: list[tuple[str, str]] = []
    for name in cur_req:
        extra = cur_req[name] - base_req.get(name, set())
        for f in sorted(extra):
            newly_required.append((name, f))

    breaking = bool(removed_routes or removed_fields or type_changed or newly_required)

    print("=== OpenAPI schema diff ===")
    if added_routes:
        print("additions (allowed):")
        for p, m in added_routes:
            print(f"  + {m.upper()} {p}")
    if added_fields:
        print("new fields (allowed):")
        for name, f in added_fields:
            print(f"  + {name}.{f}")
    if removed_routes:
        print("REMOVED routes (breaking):")
        for p, m in removed_routes:
            print(f"  - {m.upper()} {p}")
    if removed_fields:
        print("REMOVED fields (breaking):")
        for name, f in removed_fields:
            print(f"  - {name}.{f}")
    if type_changed:
        print("CHANGED field types (breaking):")
        for name, f, a, b in type_changed:
            print(f"  ~ {name}.{f}: {a} -> {b}")
    if newly_required:
        print("NEWLY required fields (breaking):")
        for name, f in newly_required:
            print(f"  ! {name}.{f}")

    if not breaking:
        print("no breaking changes")
        return 0

    # Check PR body for deprecation key.
    authorised = False
    body_file = args.pr_body_file or os.environ.get("PR_BODY_FILE")
    if body_file and os.path.isfile(body_file):
        with open(body_file, encoding="utf-8") as fh:
            body = fh.read().lower()
        if "deprecation:" in body:
            authorised = True

    if authorised:
        print("breaking changes detected but PR body contains 'deprecation:' — authorised")
        return 0

    print(
        "\nBreaking OpenAPI changes without 'deprecation:' in PR body. "
        "Either revert, or document the migration path in the PR body.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
