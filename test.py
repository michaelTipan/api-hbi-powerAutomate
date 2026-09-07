
import unicodedata

def _normalize_str(text: str) -> str:
    if not text: return ""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").strip().lower()

excel_val = "TRANSPORTE CONSTRUCCION Y MAQUINARIA SAS"
sharepoint_val1 = "TRANSPORTE CONSTRUCCION Y MAQUINARIA S.A.S."

norm_excel = _normalize_str(excel_val)
norm_sp1 = _normalize_str(sharepoint_val1)

print(f"[{norm_excel}] in [{norm_sp1}] -> {norm_excel in norm_sp1}")

