"""Los textos que la operadora ve en la UI no mencionan la UI, jobs, endpoints ni pasos internos."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

UI_MODULES = sorted(
    {
        *(ROOT / "app/application/ui").glob("*_capabilities.py"),
        *(ROOT / "app/application/ui").glob("*_resolve.py"),
        *(ROOT / "app/application/ui").glob("*_readiness.py"),
        ROOT / "app/application/ui/merge_force_rebuild.py",
        ROOT / "app/application/ui/entra_jwt.py",
        ROOT / "app/adapters/primary/http/ui/write_deps.py",
        ROOT / "app/adapters/primary/http/ui/router_v1.py",
        ROOT / "app/adapters/primary/http/ui/auth.py",
        ROOT / "app/adapters/primary/http/ui/deps.py",
    }
)

TECHNICAL = re.compile(
    r"\b(UI|endpoint|job|jobs|manifest|dry-run|dry_run|Apply|apply|Generate|Finalize|Notify|Merge|ProcessKey)\b"
    r"|/jobs/|desde la UI"
)
VISIBLE_KWARGS = {"user_message", "next_action", "reason"}


def _text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_text(v) for v in node.values)
    if isinstance(node, ast.BinOp):
        return _text(node.left) + _text(node.right)
    return ""


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _is_logging_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"logger", "logging", "log"}
    )


def _visible_texts(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    logged: set[int] = set()
    for node in ast.walk(tree):
        if _is_logging_call(node):
            logged.update(id(n) for n in ast.walk(node))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and id(node) not in logged
            and node.value.rstrip().endswith(".")
            and " " in node.value.strip()
            and node.value.strip()[:1].isupper()
        ):
            out.append((node.lineno, node.value))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith(("_REASON", "_NEXT")):
                    out.append((node.lineno, _text(node.value)))
        elif isinstance(node, ast.keyword) and node.arg in VISIBLE_KWARGS:
            out.append((node.value.lineno, _text(node.value)))
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in VISIBLE_KWARGS and v is not None:
                    out.append((v.lineno, _text(v)))
    return [(ln, t) for ln, t in out if t.strip()]


@pytest.mark.parametrize("path", UI_MODULES, ids=lambda p: p.name)
def test_textos_visibles_sin_terminos_tecnicos(path: Path):
    malos = [
        f"{path.name}:{ln}: {t}" for ln, t in _visible_texts(path) if TECHNICAL.search(t)
    ]
    assert not malos, "\n".join(malos)


def test_amortizacion_lista_sin_desde_la_ui():
    from app.application.ui import amortization_readiness, merge_readiness

    assert amortization_readiness._NEXT_START == "Puede procesar la amortización."
    assert "desde la UI" not in Path(merge_readiness.__file__).read_text(encoding="utf-8")
