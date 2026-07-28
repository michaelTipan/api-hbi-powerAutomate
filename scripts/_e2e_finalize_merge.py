"""Finalize → notify → ensure asientos → merge (con reintento) → amortización."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
WORK = Path(r"D:\CMC\HBI_Capital\_work")
ASIENTOS_DIR = Path(r"D:\CMC\HBI_Capital\asientos_prueba\generados")
CLIENTS = (
    "INFORMACION CREDITOS-CLIENTES/"
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
)

# Mapa crédito → archivo asiento a subir en carpeta ASIENTOS CONTABLES CRED {n}
ASIENTO_UPLOADS = [
    ("GEOEXCON", "CREDITO # 231", "231", "Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 231.pdf"),
    ("GEOEXCON", "CREDITO # 231", "231", "Asiento 27-JUL-2026 PAGO Y ABONO CAPITAL GEOEXCON CRED 231.pdf"),
    ("GEOEXCON", "CREDITO # 254", "254", "Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 254.pdf"),
    ("EQUINORTE", "CREDITO # 258", "258", "Asiento 27-JUL-2026 PAGO CUOTA EQUINORTE CRED 258.pdf"),
    ("EQUINORTE", "CREDITO # 264", "264", "Asiento 27-JUL-2026 PAGO CUOTA EQUINORTE CRED 264.pdf"),
    ("EQUINORTE", "CREDITO # 265", "265", "Asiento 27-JUL-2026 ABONO CAPITAL EQUINORTE CRED 265.pdf"),
    ("EQUINORTE", "CREDITO # 265", "265", "Asiento 27-JUL-2026 ABONO MORA EQUINORTE CRED 265.pdf"),
    ("AGRECAR", "2 CREDITO #37 VIGENTE", "37", "Asiento 27-JUL-2026 PAGO CUOTA AGRECAR CRED 37.pdf"),
]


def log(name: str, data: object) -> None:
    WORK.mkdir(exist_ok=True)
    path = WORK / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(name, json.dumps(data, ensure_ascii=False, default=str)[:400])


def poll(c: httpx.Client, url: str, timeout_s: int = 1200) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            r = c.get(url, timeout=90)
            if r.status_code != 200:
                print("poll_http", r.status_code, r.text[:200])
                time.sleep(8)
                continue
            body = r.json()
            st = body.get("status")
            print(time.strftime("%H:%M:%S"), "status", st)
            if st in ("completed", "failed", "error"):
                return body
        except Exception as exc:
            print("poll_err", type(exc).__name__, str(exc)[:100])
        time.sleep(8)
    raise TimeoutError(url)


def children(c, drive, fid="root"):
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("value") or []


def walk(c, drive, parts):
    cur = "root"
    for p in parts:
        hit = next((i for i in children(c, drive, cur) if i.get("name") == p), None)
        if not hit:
            raise FileNotFoundError(p)
        cur = hit["id"]
    return cur


def ensure_child_folder(c, drive, parent_id: str, name: str) -> str:
    items = children(c, drive, parent_id)
    hit = next((i for i in items if i.get("name") == name), None)
    if hit:
        return hit["id"]
    # crear vía path-content no crea carpeta; usar Graph create no expuesto.
    # Fallback: ensure-asientos endpoint + buscar de nuevo
    raise FileNotFoundError(f"folder_missing:{name}")


def upload_file(c, drive, folder_id: str, filename: str, raw: bytes) -> None:
    # path-content needs full path; item upload by creating in folder via path
    # Use PUT path-content with full relative path after resolve
    raise NotImplementedError


def main() -> None:
    with httpx.Client(timeout=180) as c:
        # --- Finalize ---
        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/finalize/queue",
            json={"bank_code": "banco_bogota"},
        )
        log("finalize_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        fin = poll(
            c,
            f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}",
        )
        log("finalize_result", fin)
        if fin.get("status") != "completed":
            print("FINALIZE FAILED — stop")
            return

        hist = (fin.get("result") or {}).get("historical_file_path")
        print("historical_file_path", hist)

        # --- Notify ---
        r = c.post(
            f"{BASE}/graph/sharepoint/notify-validar-extractos-email",
            json={"bank_code": "banco_bogota", "historical_file_path": hist},
        )
        log("notify_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        njob = r.json()["job_id"]
        notify = poll(
            c,
            f"{BASE}/graph/sharepoint/notify-validar-extractos-email/jobs/{njob}",
            timeout_s=600,
        )
        log("notify_result", notify)

        # --- Ensure asientos folders ---
        r = c.post(f"{BASE}/graph/sharepoint/ensure-asientos-contables-folders", json={})
        log("ensure_asientos_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        if r.status_code == 202:
            ej = r.json()["job_id"]
            ens = poll(
                c,
                f"{BASE}/graph/sharepoint/ensure-asientos-contables-folders/jobs/{ej}",
            )
            log("ensure_asientos_result", ens)

        # --- Upload asientos PDFs into credit asiento folders ---
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        for cliente, credito_folder, credit_digits, fname in ASIENTO_UPLOADS:
            local = ASIENTOS_DIR / fname
            if not local.exists():
                # generated may coexist with muestras; try exact
                print("missing local", fname)
                continue
            credit_path = f"{CLIENTS}/{cliente}/{credito_folder}"
            # Prefer ASIENTOS CONTABLES CRED {n}
            asiento_folder_name = f"ASIENTOS CONTABLES CRED {credit_digits}"
            rel = f"{credit_path}/{asiento_folder_name}/{fname}"
            raw = local.read_bytes()
            # encode path for path-content query
            enc_path = quote(rel, safe="")
            url = f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/path-content"
            up = c.put(
                url,
                params={"item_path": rel},
                json={"content_base64": base64.b64encode(raw).decode("ascii")},
                timeout=180,
            )
            print("upload asiento", credit_digits, fname, up.status_code, up.text[:120])

        # --- Merge sin asientos primero? already uploaded. Merge ---
        # First merge attempt
        r = c.post(f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs", json={})
        log("merge1_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        m1 = poll(
            c,
            f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{r.json()['job_id']}",
            timeout_s=900,
        )
        log("merge1_result", m1)

        # Retry merge (idempotencia / MERGE_PARCIAL recovery)
        r = c.post(f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs", json={})
        log("merge2_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        if r.status_code == 202:
            m2 = poll(
                c,
                f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{r.json()['job_id']}",
                timeout_s=900,
            )
            log("merge2_result", m2)

        # Amortization dry-run + apply
        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/dry-run/queue",
            json={},
        )
        log("amort_dry_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        if r.status_code == 202:
            ad = poll(
                c,
                f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}",
                timeout_s=900,
            )
            log("amort_dry_result", ad)

        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/apply/queue",
            json={},
        )
        log("amort_apply_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        if r.status_code == 202:
            aa = poll(
                c,
                f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}",
                timeout_s=900,
            )
            log("amort_apply_result", aa)


if __name__ == "__main__":
    main()
