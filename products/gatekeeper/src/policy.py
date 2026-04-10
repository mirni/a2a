"""High-level JSON policy DSL for Gatekeeper formal verification.

Integrators describe invariants as structured JSON instead of raw
SMT-LIB2, and the compiler deterministically lowers a :class:`JsonPolicy`
to a Z3-compatible SMT-LIB2 string that the existing Lambda verifier
consumes unchanged.

Example
-------
>>> policy = JsonPolicy.model_validate({
...     "name": "balance_conservation",
...     "variables": [
...         {"name": "alice", "type": "int"},
...         {"name": "bob", "type": "int"},
...         {"name": "total", "type": "int", "value": 100},
...     ],
...     "assertions": [
...         {"op": ">=", "args": ["alice", 0]},
...         {"op": ">=", "args": ["bob", 0]},
...         {"op": "==", "args": [{"op": "+", "args": ["alice", "bob"]}, "total"]},
...     ],
... })
>>> print(compile_policy_to_smt2(policy))
(declare-const alice Int)
(declare-const bob Int)
(declare-const total Int)
(assert (= total 100))
(assert (>= alice 0))
(assert (>= bob 0))
(assert (= (+ alice bob) total))

Supported variable types: ``int``, ``real``, ``bool``.

Supported operators:
  Arithmetic: ``+``, ``-``, ``*``, ``/``
  Comparison: ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``
  Boolean   : ``and``, ``or``, ``not``, ``=>``
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PolicyCompileError(ValueError):
    """Raised when a :class:`JsonPolicy` cannot be compiled to SMT-LIB2."""


VariableType = Literal["int", "real", "bool"]


class PolicyVariable(BaseModel):
    """A typed free variable declared in a :class:`JsonPolicy`.

    If ``value`` is supplied, the compiler emits an additional equality
    constraint ``(= name value)`` so the variable behaves like a bound
    constant.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"name": "alice", "type": "int"},
                {"name": "total", "type": "int", "value": 100},
                {"name": "rate", "type": "real"},
                {"name": "active", "type": "bool"},
            ]
        },
    )

    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: VariableType
    value: int | float | bool | None = None


class JsonPolicy(BaseModel):
    """Structured invariant specification.

    Compiles to a single SMT-LIB2 ``(check-sat)`` problem: all declared
    variables become free constants and every entry in ``assertions`` is
    wrapped in an ``(assert …)``. The solver is asked whether the set of
    assertions is satisfiable; ``sat`` means the invariant can hold,
    ``unsat`` means it is violated.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "balance_conservation",
                    "description": "Total of all balances equals supply",
                    "variables": [
                        {"name": "alice", "type": "int"},
                        {"name": "bob", "type": "int"},
                        {"name": "total", "type": "int", "value": 100},
                    ],
                    "assertions": [
                        {"op": ">=", "args": ["alice", 0]},
                        {"op": ">=", "args": ["bob", 0]},
                        {
                            "op": "==",
                            "args": [{"op": "+", "args": ["alice", "bob"]}, "total"],
                        },
                    ],
                }
            ]
        },
    )

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    variables: list[PolicyVariable] = Field(min_length=1, max_length=64)
    assertions: list[dict[str, Any]] = Field(min_length=1, max_length=256)

    @field_validator("variables")
    @classmethod
    def _unique_variable_names(cls, v: list[PolicyVariable]) -> list[PolicyVariable]:
        names = [var.name for var in v]
        if len(names) != len(set(names)):
            raise ValueError("duplicate variable names in policy")
        return v


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


_ARITH_OPS = {"+", "-", "*", "/"}
_COMP_OPS = {"<", "<=", ">", ">=", "==", "!="}
_BOOL_OPS = {"and", "or", "not", "=>"}
_ALL_OPS = _ARITH_OPS | _COMP_OPS | _BOOL_OPS

# Python-friendly → SMT-LIB2 operator names
_SMT_OP = {
    "==": "=",
    "!=": "distinct",
    "and": "and",
    "or": "or",
    "not": "not",
    "=>": "=>",
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
}

_VAR_TYPE_TO_SORT = {
    "int": "Int",
    "real": "Real",
    "bool": "Bool",
}


def compile_policy_to_smt2(policy: JsonPolicy) -> str:
    """Lower a :class:`JsonPolicy` to a deterministic SMT-LIB2 string.

    The output is stable: the same policy always yields byte-identical
    SMT-LIB2, so proof hashes remain reproducible across runs.
    """
    known: dict[str, str] = {v.name: v.type for v in policy.variables}
    lines: list[str] = []

    # Declarations first, in the order they appear in the policy.
    for var in policy.variables:
        sort = _VAR_TYPE_TO_SORT[var.type]
        lines.append(f"(declare-const {var.name} {sort})")

    # Emit constant bindings for variables that carry a `value`.
    for var in policy.variables:
        if var.value is None:
            continue
        lines.append(f"(assert (= {var.name} {_emit_literal(var.value, var.type)}))")

    # Then each user-supplied assertion.
    for assertion in policy.assertions:
        lines.append(f"(assert {_emit(assertion, known)})")

    return "\n".join(lines) + "\n"


def _emit(node: Any, known: dict[str, str]) -> str:
    """Recursively emit the S-expression form of a JSON AST ``node``.

    Terminals are integers, floats, booleans, and variable references
    (strings that must appear in ``known``).
    """
    if isinstance(node, bool):  # bool is a subclass of int — check first
        return "true" if node else "false"
    if isinstance(node, (int, float)):
        return _emit_number(node)
    if isinstance(node, str):
        if node not in known:
            raise PolicyCompileError(f"undeclared variable reference: {node!r}")
        return node
    if isinstance(node, dict):
        op = node.get("op")
        args = node.get("args")
        if op is None or args is None:
            raise PolicyCompileError(f"expression node missing 'op' or 'args': {node!r}")
        if op not in _ALL_OPS:
            raise PolicyCompileError(f"unknown operator: {op!r}")
        if not isinstance(args, list) or not args:
            raise PolicyCompileError(f"operator {op!r} requires a non-empty args list")
        smt_op = _SMT_OP[op]
        return "(" + smt_op + " " + " ".join(_emit(a, known) for a in args) + ")"
    raise PolicyCompileError(f"unsupported expression node: {node!r}")


def _emit_number(n: int | float) -> str:
    """Emit a numeric literal in SMT-LIB2 form.

    Negative numbers must be wrapped in a unary minus in SMT2:
    ``-5`` → ``(- 5)``.
    """
    if isinstance(n, int):
        return str(n) if n >= 0 else f"(- {abs(n)})"
    # Floats: use a plain decimal literal so the SMT parser accepts it.
    if n >= 0:
        return f"{n:.17g}"
    return f"(- {abs(n):.17g})"


def _emit_literal(value: int | float | bool, type_: VariableType) -> str:
    """Emit a literal for a variable constant binding."""
    if type_ == "bool":
        if not isinstance(value, bool):
            raise PolicyCompileError(f"bool variable expects true/false, got {value!r}")
        return "true" if value else "false"
    return _emit_number(value)
