"""Continúa estrés desde prepare_review + finalize (Generate ya OK 2026-07-28)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx

SPEC = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate\scripts\_stress_e2e_run.py")
spec = importlib.util.spec_from_file_location("stress", SPEC)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

BASE = mod.BASE
WORK = mod.WORK
BANK_CODE = mod.BANK_CODE
PROCESS_DATE = mod.PROCESS_DATE
CLIENTS = mod.CLIENTS
ASIENTOS_DIR = mod.ASIENTOS_DIR
REV_NAME = f"validacion_pagos_banco_bogota_{PROCESS_DATE}.xlsx"


def main() -> None:
    winners = mod.load_winners()
    rows = mod.build_bank_rows(winners)
    asiento_uploads = mod.generate_asientos(rows)

    with httpx.Client(timeout=180) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        abono_targets = [
            (r["concepto"], r["digits"])
            for r in rows
            if r.get("digits") and r["tipo"] in ("ABONO CAPITAL", "ABONO MORA")
        ]
        pago_targets = [
            {
                "concepto": r["concepto"],
                "digits": r["digits"],
                "tipo": r["tipo"],
                "monto": float(r["monto"]),
            }
            for r in rows
            if r.get("digits") and r["tipo"] in ("PAGO", "PAGO Y ABONO CAPITAL")
        ]
        mod.prepare_review(
            c, drive, REV_NAME, abono_targets=abono_targets, pago_targets=pago_targets
        )

        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/finalize/queue",
            json={"bank_code": BANK_CODE, "process_date": PROCESS_DATE},
        )
        mod.log("06b_finalize_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        fin = mod.poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}")
        mod.log("06b_finalize_result", fin)
        if fin.get("status") != "completed":
            print("FINALIZE FAILED AGAIN")
            return
        hist = (fin.get("result") or {}).get("historical_file_path")

        r = c.post(
            f"{BASE}/graph/sharepoint/notify-validar-extractos-email",
            json={"bank_code": BANK_CODE, "historical_file_path": hist},
        )
        mod.log("07b_notify_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        notify = mod.poll(
            c,
            f"{BASE}/graph/sharepoint/notify-validar-extractos-email/jobs/{r.json()['job_id']}",
            timeout_s=900,
        )
        mod.log("07b_notify_result", notify)

        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/dry-run/queue",
            json={"bank_code": BANK_CODE},
        )
        mod.log("08b_amort_too_early", {"status": r.status_code, "body": r.json() if r.content else {}})
        if r.status_code == 202:
            ae = mod.poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}")
            mod.log("08b_amort_too_early_result", ae)

        r = c.post(
            f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs",
            json={"bank_code": BANK_CODE},
        )
        mod.log("10b_merge_sin_asientos_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        if r.status_code == 202:
            m0 = mod.poll(
                c,
                f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{r.json()['job_id']}",
                timeout_s=1200,
            )
            mod.log("10b_merge_sin_asientos_result", m0)

        import base64
        from urllib.parse import quote

        for cliente, credito_folder, digits, fname in asiento_uploads:
            local = ASIENTOS_DIR / fname
            if not local.exists() or not credito_folder:
                print("skip_asiento", fname)
                continue
            rel = f"{CLIENTS}/{cliente}/{credito_folder}/ASIENTOS CONTABLES CRED {digits}/{fname}"
            up = c.put(
                f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/path-content",
                params={"item_path": rel},
                json={"content_base64": base64.b64encode(local.read_bytes()).decode("ascii")},
                timeout=180,
            )
            print("upload_asiento", digits, fname, up.status_code, up.text[:120])

        r = c.post(
            f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs",
            json={"bank_code": BANK_CODE},
        )
        mod.log("11b_merge_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        m1 = mod.poll(
            c,
            f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{r.json()['job_id']}",
            timeout_s=1800,
        )
        mod.log("11b_merge_result", m1)

        m2: dict = {}
        r = c.post(
            f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs",
            json={"bank_code": BANK_CODE},
        )
        mod.log("12b_merge2_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        if r.status_code == 202:
            m2 = mod.poll(
                c,
                f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{r.json()['job_id']}",
                timeout_s=900,
            )
            mod.log("12b_merge2_result", m2)

        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/dry-run/queue",
            json={"bank_code": BANK_CODE},
        )
        mod.log("13b_amort_dry_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        dry = mod.poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}", timeout_s=1800)
        mod.log("13b_amort_dry_result", dry)

        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/apply/queue",
            json={"bank_code": BANK_CODE},
        )
        mod.log("14b_amort_apply_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        apply = mod.poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}", timeout_s=1800)
        mod.log("14b_amort_apply_result", apply)

        apply2: dict = {}
        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/apply/queue",
            json={"bank_code": BANK_CODE},
        )
        mod.log("15b_amort_apply2_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        if r.status_code == 202:
            apply2 = mod.poll(
                c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}", timeout_s=900
            )
            mod.log("15b_amort_apply2_result", apply2)

        summary = {
            "finalize_status": fin.get("status"),
            "finalize_validated": (fin.get("result") or {}).get("validated_rows"),
            "notify_status": notify.get("status"),
            "merge_status": (m1.get("result") or {}).get("status") or m1.get("status"),
            "merge_outputs": (m1.get("result") or {}).get("outputs_count"),
            "merge_skipped": (m1.get("result") or {}).get("skipped_count"),
            "merge_already": (m2.get("result") or {}).get("already_merged"),
            "dry_can_apply": (dry.get("result") or {}).get("can_apply"),
            "dry_events": len((dry.get("result") or {}).get("events") or []),
            "apply_status": (apply.get("result") or {}).get("status") or apply.get("status"),
            "apply_tables": (apply.get("result") or {}).get("tables_uploaded_count"),
            "apply_summary": (apply.get("result") or {}).get("summary"),
            "apply_already": (apply2.get("result") or {}).get("already_applied"),
        }
        mod.log("99b_summary", summary)
        print("DONE", summary)


if __name__ == "__main__":
    main()
