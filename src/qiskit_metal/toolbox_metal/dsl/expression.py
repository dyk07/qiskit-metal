# -*- coding: utf-8 -*-
"""Safe expression and interpolation helpers for the native YAML DSL."""

from __future__ import annotations

import ast
from numbers import Number
import operator
import re
from typing import Any, Mapping

from qiskit_metal.toolbox_metal.parsing import parse_value

from .errors import DesignDslError


_INTERPOLATION_RE = re.compile(r"\$\{([^{}]+)\}")
_FULL_INTERPOLATION_RE = re.compile(r"\$\{([^{}]+)\}")
_SIMPLE_PATH_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*")
_UNIT_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_\.])"
    r"((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"\s*([A-Za-z][A-Za-z0-9_]*)\b")

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def resolve_path(ctx: Mapping[str, Any], path: str) -> Any:
    """Resolve a dotted context path such as ``options.pad_width``."""
    if path in ctx:
        return ctx[path]

    current: Any = ctx
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            try:
                current = current[index]
            except IndexError as exc:
                raise DesignDslError(
                    f"Index out of range in ${{{path}}}: {index}") from exc
            continue
        raise DesignDslError(
            f"Unknown interpolation ${{{path}}}; available roots: "
            f"{sorted(ctx)}")
    return current


def evaluate_expression(expr: str, ctx: Mapping[str, Any]) -> Any:
    """Evaluate one constrained DSL expression against local context roots."""
    expr = expr.strip()
    if not expr:
        raise DesignDslError("Empty interpolation expression")

    if _SIMPLE_PATH_RE.fullmatch(expr):
        return resolve_path(ctx, expr)

    try:
        parsed = ast.parse(_replace_unit_literals(expr, ctx), mode="eval")
    except SyntaxError as exc:
        raise DesignDslError(f"Invalid expression ${{{expr}}}: {exc.msg}") from exc
    return _eval_ast(parsed, ctx, expr)


def substitute_string(value: str,
                      ctx: Mapping[str, Any],
                      *,
                      preserve_type: bool = True) -> Any:
    """Substitute ``${...}`` expressions in a string.

    A string made of exactly one interpolation returns the evaluated object.
    Embedded interpolations are converted to text, matching the historical DSL
    behavior for values like ``"-${vars.qx}"``.
    """
    full_match = _FULL_INTERPOLATION_RE.fullmatch(value)
    if preserve_type and full_match:
        return evaluate_expression(full_match.group(1), ctx)

    def _repl(match: re.Match) -> str:
        return str(evaluate_expression(match.group(1), ctx))

    return _INTERPOLATION_RE.sub(_repl, value)


def walk_substitute(node: Any, ctx: Mapping[str, Any]) -> Any:
    """Recursively substitute expressions in YAML-derived data."""
    if isinstance(node, dict):
        return {
            substitute_string(key, ctx, preserve_type=False)
            if isinstance(key, str) else key: walk_substitute(val, ctx)
            for key, val in node.items()
        }
    if isinstance(node, list):
        return [walk_substitute(item, ctx) for item in node]
    if isinstance(node, str):
        return substitute_string(node, ctx)
    return node


def _replace_unit_literals(expr: str, ctx: Mapping[str, Any]) -> str:

    def _repl(match: re.Match) -> str:
        token = "".join(match.groups())
        parsed = parse_value(token, dict(ctx))
        if isinstance(parsed, Number) and not isinstance(parsed, bool):
            return repr(float(parsed))
        raise DesignDslError(
            f"Expression ${{{expr}}} has invalid numeric unit literal "
            f"{token!r}")

    return _UNIT_LITERAL_RE.sub(_repl, expr)


def _eval_ast(node: ast.AST, ctx: Mapping[str, Any], expr: str) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, ctx, expr)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float)) and not isinstance(
                node.value, bool):
            return node.value
        raise DesignDslError(
            f"Unsupported expression value in ${{{expr}}}: {node.value!r}")

    if isinstance(node, ast.Name):
        if node.id in ctx:
            return ctx[node.id]
        raise DesignDslError(
            f"Unknown expression name {node.id!r} in ${{{expr}}}; "
            f"available roots: {sorted(ctx)}")

    if isinstance(node, ast.Attribute):
        owner = _eval_ast(node.value, ctx, expr)
        if isinstance(owner, Mapping) and node.attr in owner:
            return owner[node.attr]
        raise DesignDslError(
            f"Unknown expression attribute {node.attr!r} in ${{{expr}}}")

    if isinstance(node, ast.Subscript):
        owner = _eval_ast(node.value, ctx, expr)
        index = _eval_subscript_index(node.slice, ctx, expr)
        try:
            return owner[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise DesignDslError(
                f"Unknown expression index {index!r} in ${{{expr}}}") from exc

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        operand = _coerce_number(_eval_ast(node.operand, ctx, expr), ctx, expr)
        return _UNARY_OPS[type(node.op)](operand)

    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _coerce_number(_eval_ast(node.left, ctx, expr), ctx, expr)
        right = _coerce_number(_eval_ast(node.right, ctx, expr), ctx, expr)
        return _BIN_OPS[type(node.op)](left, right)

    raise DesignDslError(
        f"Unsupported expression syntax in ${{{expr}}}: "
        f"{node.__class__.__name__}")


def _eval_subscript_index(node: ast.AST, ctx: Mapping[str, Any], expr: str) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)):
        return node.value
    return _eval_ast(node, ctx, expr)


def _coerce_number(value: Any, ctx: Mapping[str, Any], expr: str) -> float:
    if isinstance(value, Number) and not isinstance(value, bool):
        return float(value)

    if isinstance(value, str):
        parsed = parse_value(value, dict(ctx))
        if isinstance(parsed, Number) and not isinstance(parsed, bool):
            return float(parsed)

    raise DesignDslError(
        f"Expression ${{{expr}}} requires numeric values; got {value!r}")
