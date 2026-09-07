"""TEMP: regenera AUDIT_SOURCE_UI_DEVELOP.txt. NO COMMITAR. No toca producto."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "AUDIT_SOURCE_UI_DEVELOP.txt"

FILES = [
    "app/application/services/review_schema.py",
    "app/application/services/review_workbook_v4.py",
    "app/application/services/accounting_pdf_parser.py",
    "app/application/services/amortization_workbook.py",
    "app/application/services/extract_selection.py",
    "app/application/services/colombia_time.py",
    "app/application/services/extract_snapshot_parser.py",
    "app/application/services/asiento_lote_assignment.py",
    "app/application/use_cases/merge_composite_validado_pdfs.py",
    "app/application/use_cases/amortization_fill_dry_run.py",
    "app/application/use_cases/amortization_fill_apply.py",
    "app/application/use_cases/amortization_application_plan.py",
    "app/adapters/secondary/ms_graph_client.py",
    "app/application/services/amortization_queue_service.py",
    "app/application/use_cases/send_validar_extractos_notification.py",
    "app/application/use_cases/payment_validation_generate.py",
    "app/application/use_cases/payment_validation_finalize.py",
    "app/application/ui/amortization_operational_issues.py",
    "app/application/ui/amortization_attempt.py",
    "app/application/operational_message_policy.py",
    "app/adapters/secondary/ui_sharepoint_read.py",
    "frontend/src/domain/amortizationOperationalIssues.ts",
    "frontend/src/pages/ProcessDetailPage.tsx",
    "frontend/src/pages/DashboardPage.tsx",
    "frontend/src/api/errors.ts",
    "tests/test_merge_composite_control_workbook.py",
    "tests/test_merge_credit_items.py",
    "tests/test_amortization_fill_dry_run.py",
    "tests/test_accounting_pdf_parser.py",
    "tests/test_extract_as_of_selection.py",
    "tests/test_review_schema_v4_architecture.py",
    "tests/test_review_pipeline_v4_downstream.py",
    "tests/test_finalize_review_schema_v4.py",
    "tests/test_asiento_lote_assignment.py",
    "tests/test_pre_rc_closures.py",
    "tests/test_ms_graph_put_bytes_if_match.py",
    "scripts/_audit_diagnostico_tmp.py",
]


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")


def main() -> None:
    chunks: list[str] = []
    chunks.append("AUDIT_SOURCE_UI_DEVELOP")
    chunks.append(f"generated_at_utc={datetime.now(timezone.utc).isoformat()}")
    chunks.append("NO SECRETOS. Worktree ui-develop. NO COMMIT.")
    chunks.append("\n===== GIT HEAD =====\n")
    chunks.append(run(["git", "rev-parse", "HEAD"]))
    chunks.append(run(["git", "rev-parse", "--short", "HEAD"]))
    chunks.append(run(["git", "branch", "--show-current"]))
    chunks.append(run(["git", "log", "-1", "--format=%H%n%s%n%an %ae%n%ci"]))
    chunks.append("\n===== git status --short =====\n")
    chunks.append(run(["git", "status", "--short"]))
    chunks.append("\n===== git diff --stat HEAD =====\n")
    chunks.append(run(["git", "diff", "--stat", "HEAD"]))
    chunks.append("\n===== git diff HEAD (tracked) =====\n")
    chunks.append(run(["git", "diff", "HEAD"]))
    chunks.append("\n===== ARCHIVOS RELEVANTES (contenido) =====\n")
    for rel in FILES:
        path = ROOT / rel
        chunks.append("\n" + "=" * 80 + f"\nFILE {rel}\n" + "=" * 80 + "\n")
        if not path.is_file():
            chunks.append("(MISSING)\n")
            continue
        size = path.stat().st_size
        if size > 900_000:
            chunks.append(f"(OMITIDO por tamaño {size} bytes)\n")
            continue
        chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    chunks.append("\n===== CASOS-NUEVOS (nombres, no binario) =====\n")
    casos = ROOT / "casos-nuevos"
    if casos.is_dir():
        for p in sorted(casos.iterdir()):
            chunks.append(f"{p.name} size={p.stat().st_size}\n")
    OUT.write_text("".join(chunks), encoding="utf-8")
    print(f"wrote {OUT} bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()
