import json
from urllib.parse import quote

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
CLIENTS_BASE = (
    "INFORMACION CREDITOS-CLIENTES/02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
)
TARGETS = [
    "ACIMOR",
    "MINCIVIL",
    "INVERSIONES Y PROYECTOS MIOS",
    "GEOEXCON",
    "EQUINORTE",
    "AGRECAR",
]


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
        items = children(c, drive, cur)
        hit = next((i for i in items if i.get("name") == p), None)
        if not hit:
            raise SystemExit(f"missing {p}")
        cur = hit["id"]
    return cur


def main():
    with httpx.Client() as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env", timeout=60).json()["resolved"][
            "drive_id"
        ]
        base_id = walk(c, drive, CLIENTS_BASE.split("/"))
        root = children(c, drive, base_id)
        by = {i["name"]: i for i in root if "folder" in i}
        out = {}
        for t in TARGETS:
            hit = None
            for name, it in by.items():
                if t.upper() in name.upper() or name.upper() in t.upper():
                    hit = it
                    break
            if not hit:
                out[t] = "NOT FOUND"
                continue
            kids = children(c, drive, hit["id"])
            summary = []
            for k in kids:
                kind = "folder" if "folder" in k else "file"
                entry = {"name": k.get("name"), "kind": kind}
                if kind == "folder":
                    sub = children(c, drive, k["id"])
                    entry["children"] = [
                        {
                            "name": s.get("name"),
                            "kind": ("folder" if "folder" in s else "file"),
                        }
                        for s in sub[:40]
                    ]
                summary.append(entry)
            out[t] = {"folder": hit["name"], "entries": summary}
        from pathlib import Path

        out_path = Path(__file__).resolve().parents[2] / "client_trees.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK {out_path}")


if __name__ == "__main__":
    main()
