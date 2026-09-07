"""Smoke post-deploy sandbox UI (sin secretos en stdout)."""
from __future__ import annotations

from pathlib import Path

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
ENV_PATH = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env")
EXPECTED_BUILD = "u4-rc-sandbox-ui-enabled-a676484"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> None:
    keys = load_env(ENV_PATH)
    h = httpx.get(f"{BASE}/health", timeout=60).json()
    print(
        "HEALTH",
        h.get("status"),
        h.get("build"),
        h.get("environment"),
        h.get("ui_enabled"),
    )
    assert h.get("build") == EXPECTED_BUILD, h.get("build")
    assert h.get("environment") == "sandbox"
    assert h.get("ui_enabled") is True

    api = (
        keys.get("API_HTTP_KEY")
        or keys.get("API_KEY")
        or keys.get("PAYMENT_VALIDATION_API_KEY")
        or keys.get("GRAPH_API_KEY")
        or ""
    )
    user = keys.get("UI_LOCAL_USERNAME", "operador_hbi")
    pw = keys.get("UI_LOCAL_PASSWORD") or keys.get("UI_OPERATOR_PASSWORD") or ""
    print("API_KEY_PRESENT", bool(api), "PW_PRESENT", bool(pw))

    if pw:
        with httpx.Client(base_url=BASE, timeout=120, headers={"Origin": BASE}) as c:
            r = c.post("/api/ui/v1/auth/login", json={"username": user, "password": pw})
            print("login", r.status_code)
            r.raise_for_status()
            b = c.get("/api/ui/v1/bootstrap")
            print("bootstrap", b.status_code)
            b.raise_for_status()
            caps = b.json().get("capabilities") or {}
            for name in ("write", "finalize", "notify", "merge", "amortization"):
                node = caps.get(name) or {}
                allowed = node.get("allowed") if isinstance(node, dict) else None
                print(name, allowed)
                assert allowed is True, name

    if api:
        r = httpx.get(
            f"{BASE}/graph/diagnostics/paths-probe",
            headers={"X-API-Key": api},
            timeout=180,
        )
        print("paths-probe", r.status_code)
        r.raise_for_status()
        j = r.json()
        blob = str(j).casefold()
        assert "comware pruebas" in blob, "paths-probe debe resolver PRUEBAS en sandbox"
        print("paths-probe OK (PRUEBAS presente)")


if __name__ == "__main__":
    main()
