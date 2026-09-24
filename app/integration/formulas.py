"""
Formula measures: ratios and derived KPIs computed from their components.

    nrw_pct               = nrw / vol_produced * 100
    collection_efficiency = cash_collected / amt_billed * 100
    cost_per_m3           = opex_actual / revenue_water

A formula is evaluated per organisational unit and period, *after* its
components have been rolled up. Organisation-level NRW % is therefore total NRW
over total production (volume-weighted), never an average of scheme percentages.

Expressions are parsed with ``ast`` and only a whitelist is allowed: numbers,
catalogue codes, + - * /, unary minus, parentheses and min/max/abs. Nothing is
ever passed to ``eval``. Division by zero, or a missing component, yields no
value (missing), never zero.
"""
from __future__ import annotations

import ast
import operator
from typing import Callable, Iterable

MAX_LENGTH = 500
_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS: dict[str, Callable] = {"min": min, "max": max, "abs": abs}


class FormulaError(ValueError):
    pass


def _check(node: ast.AST) -> None:
    if isinstance(node, ast.Expression):
        return _check(node.body)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        _check(node.left)
        _check(node.right)
        return
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _check(node.operand)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return
    if isinstance(node, ast.Name):
        if node.id in _FUNCS:
            raise FormulaError(f"'{node.id}' is a function; call it as {node.id}(...)")
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        if node.keywords or not node.args:
            raise FormulaError(f"{node.func.id}() takes positional arguments only")
        for arg in node.args:
            _check(arg)
        return
    raise FormulaError(f"not allowed in a formula: {ast.dump(node)[:60]}")


def parse(expr: str) -> ast.Expression:
    if not expr or not expr.strip():
        raise FormulaError("formula is empty")
    if len(expr) > MAX_LENGTH:
        raise FormulaError(f"formula longer than {MAX_LENGTH} characters")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"syntax error: {exc.msg}") from None
    _check(tree)
    return tree


def references(expr: str) -> set[str]:
    """Catalogue codes a formula reads."""
    return {n.id for n in ast.walk(parse(expr)) if isinstance(n, ast.Name) and n.id not in _FUNCS}


class _Missing(Exception):
    """Raised inside evaluation for a missing input or division by zero."""


def evaluate(expr: str, values: dict[str, float | None]) -> float | None:
    """Value of the formula, or None if an input is missing or a division by zero occurs."""
    tree = parse(expr)

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            v = values.get(node.id)
            if v is None:
                raise _Missing
            return float(v)
        if isinstance(node, ast.UnaryOp):
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.BinOp):
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise _Missing
            return _BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.Call):
            return float(_FUNCS[node.func.id](*[ev(a) for a in node.args]))
        raise FormulaError("unexpected node")  # unreachable after _check

    try:
        return ev(tree)
    except _Missing:
        return None


def validate(code: str, expr: str, known: set[str], formulas: dict[str, str]) -> set[str]:
    """Check a formula against the catalogue; returns its references.

    ``formulas`` maps every other formula measure to its expression, so chains
    (a formula using another formula) are allowed but cycles are rejected.
    """
    refs = references(expr)
    unknown = sorted(refs - known)
    if unknown:
        raise FormulaError(f"unknown measure(s): {', '.join(unknown)}")
    graph = {**formulas, code: expr}

    def visit(node: str, path: tuple[str, ...]):
        if node in path:
            raise FormulaError("circular formula: " + " → ".join((*path, node)))
        if node in graph:
            for ref in references(graph[node]):
                visit(ref, (*path, node))

    visit(code, ())
    return refs


def check_catalogue(formulas: dict[str, str], known: Iterable[str]) -> None:
    known = set(known)
    for code, expr in formulas.items():
        validate(code, expr, known, {k: v for k, v in formulas.items() if k != code})
