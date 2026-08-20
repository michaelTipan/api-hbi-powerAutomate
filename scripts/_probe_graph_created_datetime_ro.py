"""GET-only probe via authorized API Graph proxy (sandbox PRUEBAS folder).

Uses existing GET endpoints only:
  GET /graph/diagnostics/paths-probe
  GET /graph/sharepoint/drives/{drive_id}/children?folder_item_id=

Does NOT call PUT/POST/PATCH/DELETE/item-content.
Does not print API keys or secrets.
NO COMMIT.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT.parent / "api-hbi-powerAutomate.env"
BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
CLIENTS_BASE = (
    "INFORMACION CREDITOS-CLIENTES/"
    "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
)
SKIP = {
    "00 CARGA TRANSACCIONES BANCO",
    "01 VALIDACION PAGOS",
    "02 VALIDACION PAGOS",
    "EQUINORTE",
    "EQUIPOS DEL NORTE",
}


def load_api_key() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("API_HTTP_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("API_HTTP_KEY missing")


def children(c: httpx.Client, drive: str, fid: str = "root") -> list[dict]:
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
        timeout=120,
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


def walk(c: httpx.Client, drive: str, parts: list[str]) -> str:
    cur = "root"
    for p in parts:
        items = children(c, drive, cur)
        hit = next((i for i in items if i.get("name") == p), None)
        if not hit:
            raise FileNotFoundError(p)
        cur = str(hit["id"])
    return cur


def present(obj: dict) -> dict[str, bool]:
    fsi = obj.get("fileSystemInfo") if isinstance(obj.get("fileSystemInfo"), dict) else {}
    return {
        "id": bool(obj.get("id")),
        "name": bool(obj.get("name")),
        "createdDateTime": bool(obj.get("createdDateTime")),
        "lastModifiedDateTime": bool(obj.get("lastModifiedDateTime")),
        "eTag": bool(obj.get("eTag")),
        "cTag": bool(obj.get("cTag")),
        "size": obj.get("size") is not None,
        "webUrl": bool(obj.get("webUrl")),
        "fileSystemInfo": bool(fsi),
        "fileSystemInfo.createdDateTime": bool(fsi.get("createdDateTime")),
        "fileSystemInfo.lastModifiedDateTime": bool(fsi.get("lastModifiedDateTime")),
    }


def sanitize(obj: dict, idx: int, kind: str) -> dict:
    fsi = obj.get("fileSystemInfo") if isinstance(obj.get("fileSystemInfo"), dict) else {}
    etag = str(obj.get("eTag") or "")
    ctag = str(obj.get("cTag") or "")
    digest = hashlib.sha256(str(obj.get("name") or "").encode("utf-8")).hexdigest()[:8]
    return {
        "alias": f"{kind}-{idx}-{digest}",
        "present": present(obj),
        "createdDateTime": obj.get("createdDateTime"),
        "lastModifiedDateTime": obj.get("lastModifiedDateTime"),
        "fileSystemInfo.createdDateTime": fsi.get("createdDateTime"),
        "fileSystemInfo.lastModifiedDateTime": fsi.get("lastModifiedDateTime"),
        "size": obj.get("size"),
        "eTag_prefix": etag[:28],
        "cTag_prefix": ctag[:28],
        "raw_top_level_keys": sorted(obj.keys()),
        "fileSystemInfo_keys": sorted(fsi.keys()) if fsi else [],
    }


def main() -> None:
    key = load_api_key()
    headers = {"X-API-Key": key}
    with httpx.Client(headers=headers, timeout=180) as c:
        probe = c.get(f"{BASE}/graph/diagnostics/paths-probe")
        probe.raise_for_status()
        pj = probe.json()
        drive = (pj.get("operations_site") or {}).get("drive_id")
        env = pj.get("active_environment") or pj.get("environment")
        clients_path = (
            (pj.get("operations_site") or {}).get("clients_base_path")
            or pj.get("GRAPH_CLIENTS_BASE_PATH")
        )
        print("active_environment=", env)
        print("paths_probe_clients_base=", clients_path)
        print("walk_target=", CLIENTS_BASE)
        print("http_method=GET")
        print(
            "proxy_endpoint=GET /graph/sharepoint/drives/{drive_id}/children"
            "?folder_item_id={id}"
        )
        print(
            "graph_endpoint=GET /drives/{drive_id}/items/{folder_item_id}/children"
        )
        print("graph_$select=(none — proxy does not pass $select)")

        root_id = walk(c, drive, CLIENTS_BASE.split("/"))
        top = children(c, drive, root_id)
        clients = [
            it
            for it in top
            if "folder" in it
            and str(it.get("name") or "") not in SKIP
            and not str(it.get("name") or "").upper().startswith("EQUINORTE")
        ]
        pdfs: list[dict] = []
        tables: list[dict] = []
        for cit in clients:
            if len(pdfs) >= 3 and tables:
                break
            ckids = children(c, drive, str(cit["id"]))
            for unit in ckids:
                if "folder" not in unit:
                    continue
                uname = str(unit.get("name") or "")
                if uname.casefold() in {"extractos", "asientos contables"}:
                    continue
                ukids = children(c, drive, str(unit["id"]))
                if not tables:
                    for f in ukids:
                        n = str(f.get("name") or "").lower()
                        if n.endswith((".xlsx", ".xlsm")) and f.get("file"):
                            tables.append(f)
                            break
                for f in ukids:
                    if "folder" in f and str(f.get("name") or "").casefold() == "extractos":
                        exs = children(c, drive, str(f["id"]))
                        for ex in exs:
                            en = str(ex.get("name") or "").lower()
                            if en.endswith(".pdf") and "file" in ex:
                                pdfs.append(ex)
                                if len(pdfs) >= 3:
                                    break
                if len(pdfs) >= 3 and tables:
                    break

        report = {
            "pdf_count": len(pdfs),
            "pdfs": [sanitize(p, i, "pdf") for i, p in enumerate(pdfs[:3], start=1)],
            "table_xlsx": sanitize(tables[0], 1, "xlsx") if tables else None,
            "generate_code_select": "(none — payment_validation_generate._get_drive_folder_children GET children)",
            "ui_read_select": "id,name,webUrl,eTag,cTag,size,lastModifiedDateTime",
            "property_to_add_for_generate_if_select_introduced": "createdDateTime,fileSystemInfo",
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
