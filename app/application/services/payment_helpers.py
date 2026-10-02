from dataclasses import dataclass
from datetime import datetime, date
import re
import unicodedata
from io import BytesIO
from typing import Any

def _normalize_str(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.strip().lower()

def parse_bank_date(raw_date: any, process_date: date) -> date:
    if isinstance(raw_date, datetime):
        return raw_date.date()
    if isinstance(raw_date, date):
        return raw_date
        
    if not isinstance(raw_date, str):
        raise ValueError("bank_date_parse_error")
        
    text = raw_date.strip()
    
    # Try text match like "30/12/2025" or "30-12-2025"
    m_full = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", text)
    if m_full:
        return date(int(m_full.group(3)), int(m_full.group(2)), int(m_full.group(1)))
        
    # Try text match like "30-dic"
    m_short = re.match(r"^(\d{1,2})-(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)$", text.lower())
    if m_short:
        day = int(m_short.group(1))
        months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
        month = months.index(m_short.group(2)) + 1
        return date(process_date.year, month, day)
        
    raise ValueError("bank_date_parse_error")

def parse_bank_amount(raw_amount: any) -> float:
    if isinstance(raw_amount, (int, float)):
        return float(raw_amount)
        
    if not isinstance(raw_amount, str):
        raise ValueError("bank_amount_parse_error")
        
    text = raw_amount.strip()
    if not text:
        raise ValueError("bank_amount_parse_error")
        
    # Eliminar $, espacios, y puntos de miles
    text = text.replace("$", "").replace(" ", "").replace(".", "")
    # Reemplazar coma de decimales por punto
    text = text.replace(",", ".")
    
    try:
        return float(text)
    except ValueError:
        raise ValueError("bank_amount_parse_error")

def extract_client_from_bank_row(concepto: str | None, transaccion: str | None) -> str:
    c = str(concepto).strip() if concepto else ""
    t = str(transaccion).strip() if transaccion else ""
    
    if c and c.lower() != "nan":
        return c
    if t and t.lower() != "nan":
        return t
        
    raise ValueError("customer_not_found")


_IDENTIFICAR_TOKEN = re.compile(r"\bidentificar\b")


def is_unidentified_bank_partida(concepto: Any = None, transaccion: Any = None) -> bool:
    """Fila banco sin cliente: Concepto/Transacción con la palabra «identificar».

    Cubre «Partida x identificar», «Partida x identificar 1» y «POR IDENTIFICAR».
    No cubre consignaciones a devolver ni un nombre de cliente mal escrito.
    """
    for raw in (concepto, transaccion):
        if raw is None:
            continue
        folded = _normalize_str(str(raw))
        if folded and _IDENTIFICAR_TOKEN.search(folded):
            return True
    return False

_STATEMENT_NAME_CREDIT_RE = re.compile(
    r"(?i)(?<![a-z])(?:cr[eé]dito|cred|obligaci[oó]n?|oblig)\.?[ \t_\-]*"
    r"(?:#|n[o°º]\.?)?[ \t_\-:]*0*(\d{1,6})(?!\d)(?![-/._]\d)"
)
_STATEMENT_NAME_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)")
_STATEMENT_NAME_DMY_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[-_./](\d{1,2})[-_./](\d{4})(?!\d)")


def _statement_name_date(filename: str) -> date | None:
    for rx, order in ((_STATEMENT_NAME_ISO_DATE_RE, "ymd"), (_STATEMENT_NAME_DMY_DATE_RE, "dmy")):
        m = rx.search(filename)
        if not m:
            continue
        a, b, c = (int(g) for g in m.groups())
        y, mo, d = (a, b, c) if order == "ymd" else (c, b, a)
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def parse_statement_name(filename: str) -> tuple[date | None, str | None]:
    # Extracto YYYY-MM-DD CREDITO # NNN.pdf
    m_new = re.search(r"(?i)extracto\s+(\d{4}-\d{2}-\d{2})\s+cr[eé]dito\s*#\s*(\d+)", filename)
    if m_new:
        d = datetime.strptime(m_new.group(1), "%Y-%m-%d").date()
        return d, m_new.group(2)
        
    # Extracto Abril 20-03-2026 Obligacio # 265.pdf
    m_old = re.search(r"(?i)extracto\s+[a-z]+\s+(\d{2}-\d{2}-\d{4})\s+obligaci[oó]n?\s*#\s*(\d+)", filename)
    if m_old:
        d = datetime.strptime(m_old.group(1), "%d-%m-%Y").date()
        return d, m_old.group(2)

    # Variantes de nombre: «extracto_2026-09-30_credito_148.pdf», «Extracto Crédito No. 0148»,
    # «EXTRACTO OBLIGACION 265 20-03-2026.pdf». Solo cuenta un número junto a crédito/obligación.
    if re.search(r"(?i)extracto", filename or ""):
        m_cred = _STATEMENT_NAME_CREDIT_RE.search(filename)
        if m_cred:
            return _statement_name_date(filename), str(int(m_cred.group(1)))

    return None, None

_FECHA_NEAR_WINDOW = 120
_DATE_TOKEN_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}")
_DESEMBOLSO_RE = re.compile(r"desembolso", re.IGNORECASE)
# Anclas de plantilla HBI: las de fecha límite primero; alias «FECHA DE PAGO»
# (plantilla nueva) después de límite y antes de «fecha de vencimiento» (más
# ambiguo en pie de página). PAGO INMEDIATO solo si esa etiqueta no trae fecha
# usable (extractos en mora con capa de texto desordenada). «vencimiento»
# suelto no es ancla: llevaba a tomar otra fecha del extracto.
# No incluir «fecha pago» sin «de»: no aparece en prod y es demasiado genérico.
_PRIMARY_FECHA_LIMITE_LABELS = (
    r"fecha\s+l[ií]mite\s+de\s+pago",
    r"fecha\s+l[ií]mite\s+pago",
    r"fecha\s+de\s+pago",
    r"fecha\s+de\s+vencimiento",
)
_SECONDARY_FECHA_LIMITE_LABELS = (r"pago\s+inmediato",)
_GENERIC_FECHA_LIMITE_LABELS = (r"fecha\s+l[ií]mite\b",)

# Texto con forma de fecha pero mal leído («3O/O9/2026», «30//09/2026»): decide
# igual que una fecha (falla), para no saltar a la siguiente fecha del extracto.
_DATE_SEP = r"[ \t]?[/\-]{1,2}[ \t]?"
_DATE_LIKE_TOKEN_RE = re.compile(
    r"(?<![0-9/\-])(?:"
    rf"[0-9OoIl]{{1,2}}{_DATE_SEP}[0-9OoIl]{{1,2}}{_DATE_SEP}[0-9OoIl]{{4}}"
    rf"|[0-9OoIl]{{4}}{_DATE_SEP}[0-9OoIl]{{1,2}}{_DATE_SEP}[0-9OoIl]{{1,2}}"
    r")(?![0-9])"
)

FECHA_LIMITE_LABEL_NOT_FOUND = "fecha_limite_label_not_found"
FECHA_LIMITE_UNREADABLE = "fecha_limite_unreadable"
FECHA_LIMITE_INVALID_DATE = "fecha_limite_invalid_date"


@dataclass(frozen=True)
class FechaLimiteReading:
    """Resultado de leer la fecha límite: la fecha, o la causa por la que no se pudo."""

    fecha: date | None
    cause: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class _DateCandidate:
    start: int
    raw: str
    fecha: date | None
    cause: str | None


def fecha_limite_problem_text(cause: str | None, text: str | None = None) -> str:
    """Frase para el operador (sin códigos) que explica por qué no se leyó la fecha límite."""
    shown = " ".join(str(text or "").split())[:60]
    if cause == FECHA_LIMITE_LABEL_NOT_FOUND:
        return "no se encontró el rótulo «Fecha límite de pago» en el extracto"
    if cause == FECHA_LIMITE_INVALID_DATE:
        if shown:
            return f"la fecha límite del extracto ({shown}) no existe en el calendario"
        return "la fecha límite del extracto no existe en el calendario"
    if shown:
        return f"la fecha límite del extracto no se puede leer (se leyó «{shown}»)"
    return "la fecha límite del extracto no se puede leer"


def _parse_limite_date_token(token: str) -> date | None:
    """
    Interpreta fechas de extracto: ISO yyyy-mm-dd o europeo dd/mm/yyyy y dd-mm-yyyy
    (día primero; nunca mm/dd/yyyy).
    """
    token = token.strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", token)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", token)
    if not m:
        return None
    day, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if mo < 1 or mo > 12 or day < 1 or day > 31:
        return None
    try:
        return date(y, mo, day)
    except ValueError:
        return None


def _is_desembolso_contaminated(snippet: str, token_start: int) -> bool:
    """True solo si *esta* fecha es la de desembolso, no una posterior en el mismo recorte."""
    left = snippet[:token_start]
    matches = list(_DESEMBOLSO_RE.finditer(left))
    if not matches:
        return False
    between = left[matches[-1].end() :]
    if _DATE_TOKEN_RE.search(between):
        return False
    return len(between) <= 24


def _date_candidates(snippet: str) -> list[_DateCandidate]:
    """Fechas (válidas, inexistentes o mal leídas) en orden de lectura, sin la de desembolso."""
    if not snippet:
        return []
    found: list[_DateCandidate] = []
    strict_spans: list[tuple[int, int]] = []
    for m in _DATE_TOKEN_RE.finditer(snippet):
        strict_spans.append((m.start(), m.end()))
        fecha = _parse_limite_date_token(m.group(0))
        if fecha is not None:
            found.append(_DateCandidate(m.start(), m.group(0), fecha, None))
            continue
        # Fecha inexistente solo si el token está aislado (no un trozo de NIT/cuenta).
        left_ok = m.start() == 0 or not snippet[m.start() - 1].isdigit()
        right_ok = m.end() >= len(snippet) or not snippet[m.end()].isdigit()
        if left_ok and right_ok:
            found.append(_DateCandidate(m.start(), m.group(0), None, FECHA_LIMITE_INVALID_DATE))
    for m in _DATE_LIKE_TOKEN_RE.finditer(snippet):
        if any(s < m.end() and m.start() < e for s, e in strict_spans):
            continue
        raw = m.group(0)
        if sum(ch.isdigit() for ch in raw) < 4:
            continue
        if raw[0].isalpha() and m.start() > 0 and snippet[m.start() - 1].isalpha():
            continue
        compact = re.sub(r"[ \t]", "", raw)
        if _DATE_TOKEN_RE.fullmatch(compact):
            fecha = _parse_limite_date_token(compact)
            cause = None if fecha is not None else FECHA_LIMITE_INVALID_DATE
            found.append(_DateCandidate(m.start(), raw, fecha, cause))
        else:
            found.append(_DateCandidate(m.start(), raw, None, FECHA_LIMITE_UNREADABLE))
    found = [c for c in found if not _is_desembolso_contaminated(snippet, c.start)]
    found.sort(key=lambda c: c.start)
    return found


def _reading_from_candidate(cand: _DateCandidate) -> FechaLimiteReading:
    if cand.fecha is not None:
        return FechaLimiteReading(cand.fecha)
    return FechaLimiteReading(None, cand.cause, cand.raw)


def _decide_after_or_before_label(
    pdf_text: str,
    match: re.Match[str],
    *,
    allow_before: bool,
) -> FechaLimiteReading | None:
    """La primera fecha *después* de la ancla decide; si no hay, la inmediatamente *antes*.

    Una fecha inexistente o ilegible junto a la ancla también decide (falla): nunca se
    salta a otra fecha cercana.
    """
    tail = pdf_text[match.end() : match.end() + _FECHA_NEAR_WINDOW]
    after = _date_candidates(tail)
    if after:
        return _reading_from_candidate(after[0])
    if not allow_before:
        return None
    head = pdf_text[max(0, match.start() - _FECHA_NEAR_WINDOW) : match.start()]
    before = _date_candidates(head)
    if before:
        return _reading_from_candidate(before[-1])
    return None


def _decide_near_labels(
    pdf_text: str,
    exprs: tuple[str, ...],
    *,
    allow_before: bool,
) -> FechaLimiteReading | None:
    for expr in exprs:
        rx = re.compile(expr, re.IGNORECASE)
        for mat in rx.finditer(pdf_text):
            decided = _decide_after_or_before_label(
                pdf_text, mat, allow_before=allow_before
            )
            if decided is not None:
                return decided
    return None


def _text_after_first_label(pdf_text: str) -> str | None:
    for expr in (
        *_PRIMARY_FECHA_LIMITE_LABELS,
        *_SECONDARY_FECHA_LIMITE_LABELS,
        *_GENERIC_FECHA_LIMITE_LABELS,
    ):
        m = re.search(expr, pdf_text, re.IGNORECASE)
        if m:
            tail = " ".join(pdf_text[m.end() : m.end() + 40].split())
            return tail.strip(" :") or None
    return None


def _has_fecha_limite_label(pdf_text: str) -> bool:
    return any(
        re.search(expr, pdf_text, re.IGNORECASE)
        for expr in (
            *_PRIMARY_FECHA_LIMITE_LABELS,
            *_SECONDARY_FECHA_LIMITE_LABELS,
            *_GENERIC_FECHA_LIMITE_LABELS,
        )
    )


def read_fecha_limite_pago_from_pdf_text(pdf_text: str) -> FechaLimiteReading:
    """
    Lee la fecha límite de pago desde texto ya extraído (p. ej. pdfplumber).

    Anclas en orden: «Fecha límite de pago» (y variantes) y alias «FECHA DE PAGO»;
    luego «PAGO INMEDIATO» (extractos en mora con texto desordenado); luego
    «Fecha límite» genérica. La primera fecha junto a la ancla decide: si es
    inexistente (30/02/2026) o ilegible (3O/O9/2026) devuelve esa causa en vez de
    tomar otra fecha del extracto. Nunca usa la fecha de desembolso.
    Formatos yyyy-mm-dd, dd/mm/yyyy y dd-mm-yyyy (día/mes/año).
    """
    if not pdf_text or not pdf_text.strip():
        return FechaLimiteReading(None, FECHA_LIMITE_UNREADABLE, None)
    for exprs in (
        _PRIMARY_FECHA_LIMITE_LABELS,
        _SECONDARY_FECHA_LIMITE_LABELS,
        _GENERIC_FECHA_LIMITE_LABELS,
    ):
        decided = _decide_near_labels(pdf_text, exprs, allow_before=True)
        if decided is not None:
            return decided
    if _has_fecha_limite_label(pdf_text):
        return FechaLimiteReading(None, FECHA_LIMITE_UNREADABLE, _text_after_first_label(pdf_text))
    return FechaLimiteReading(None, FECHA_LIMITE_LABEL_NOT_FOUND, None)


def extract_fecha_limite_pago_from_pdf_text(pdf_text: str) -> date | None:
    """Fecha límite desde texto; None si no se pudo leer (ver ``read_fecha_limite_pago_from_pdf_text``)."""
    if not pdf_text:
        return None
    return read_fecha_limite_pago_from_pdf_text(pdf_text).fecha


_FECHA_LIMITE_CELL_RE = re.compile(
    r"(?i)(?:fecha\s+l[ií]mite(?:\s+de)?\s+pago|fecha\s+de\s+pago)"
)


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def _first_candidate_in_text(snippet: str) -> _DateCandidate | None:
    """Primera fecha (válida o no) en un fragmento, sin tomar desembolso inmediato."""
    cands = _date_candidates(snippet)
    return cands[0] if cands else None


def _read_fecha_limite_from_table_rows(
    tables: list[list[list[object | None]]],
) -> FechaLimiteReading | None:
    """
    Plan A: fila visual «Fecha límite de pago | <fecha>».
    La primera fecha de esa fila decide; si es inexistente o ilegible devuelve la
    causa (no busca otra fecha). None si ninguna fila con rótulo trae fecha.
    """
    for table in tables:
        if not table:
            continue
        for row in table:
            cells = [_cell_text(c) for c in (row or [])]
            if not any(_FECHA_LIMITE_CELL_RE.search(c) for c in cells):
                continue
            # 1) Fecha en otra celda de la misma fila (layout HBI típico).
            for cell in cells:
                m = _FECHA_LIMITE_CELL_RE.search(cell)
                # Misma celda del rótulo: solo la parte *después* del rótulo.
                cand = _first_candidate_in_text(cell[m.end() :] if m else cell)
                if cand is not None:
                    return _reading_from_candidate(cand)
    return None


def _extract_fecha_limite_from_table_rows(
    tables: list[list[list[object | None]]],
) -> date | None:
    reading = _read_fecha_limite_from_table_rows(tables)
    return reading.fecha if reading is not None else None


def _pdfplumber_tables_and_text(pdf_bytes: bytes) -> tuple[list[list[list[object | None]]], str]:
    """Abre el PDF una sola vez con pdfplumber: tablas + texto en orden visual."""
    import pdfplumber

    tables: list[list[list[object | None]]] = []
    text_parts: list[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                tables.append(table)
            t = page.extract_text() or ""
            if t:
                text_parts.append(t)
    return tables, "\n".join(text_parts)


def read_fecha_limite_pago_from_pdf(pdf_bytes: bytes) -> FechaLimiteReading:
    """
    Fecha límite de pago **solo** vía pdfplumber (contrato de producto).

    1) Tabla: celda/fila «Fecha límite de pago» o «FECHA DE PAGO» → fecha de esa fila.
    2) Texto pdfplumber + anclas (Fecha límite / FECHA DE PAGO, luego PAGO INMEDIATO).
    Fail-closed si no hay text layer, la celda es basura o la fecha es inválida; en ese
    caso devuelve la causa y no busca otra fecha en el texto.
    No usa pypdf para este campo (el stream plano desordena celdas HBI).
    """
    if not pdf_bytes or len(pdf_bytes) < 32:
        return FechaLimiteReading(None, FECHA_LIMITE_UNREADABLE, None)
    try:
        tables, text = _pdfplumber_tables_and_text(pdf_bytes)
    except Exception:
        return FechaLimiteReading(None, FECHA_LIMITE_UNREADABLE, None)
    table_reading = _read_fecha_limite_from_table_rows(tables)
    if table_reading is not None:
        return table_reading
    if not (text or "").strip():
        return FechaLimiteReading(None, FECHA_LIMITE_UNREADABLE, None)
    return read_fecha_limite_pago_from_pdf_text(text)


def extract_fecha_limite_pago_from_pdf(pdf_bytes: bytes) -> date | None:
    """Fecha límite o None (ver ``read_fecha_limite_pago_from_pdf`` para la causa)."""
    return read_fecha_limite_pago_from_pdf(pdf_bytes).fecha


def extract_from_pdf_fallback(pdf_text: str) -> tuple[str | None, date | None, float | None]:
    cred, d, total = None, None, None
    
    m_cred = re.search(r"(?i)No\.?\s*Obligaci[oó]n\s+(\d+)", pdf_text)
    if m_cred:
        cred = m_cred.group(1)

    d = extract_fecha_limite_pago_from_pdf_text(pdf_text)
    m_total = re.search(r"(?i)TOTAL\s+A\s+PAGAR\s*\$?\s*([\d\.\,]+)", pdf_text)
    if m_total:
        try:
            val_str = m_total.group(1).replace(".", "").replace(",", ".")
            total = float(val_str)
        except ValueError:
            pass
            
    return cred, d, total


def _is_amortization_excel_filename(filename: str) -> bool:
    """Tabla operativa = solo Excel (no PDFs informativos con 'tabla' en el nombre)."""
    if not filename or filename.startswith("~$"):
        return False
    lower = filename.lower()
    return lower.endswith(".xlsx") or lower.endswith(".xlsm") or lower.endswith(".xls")


def filter_amortization_excel_filenames(files: list[str]) -> list[str]:
    return [f for f in files if f and _is_amortization_excel_filename(f)]


def extract_credit_id_from_extract_pdf_text(pdf_text: str) -> str | None:
    """
    Número de obligación/crédito legible en texto de extracto (modo cliente plano / refuerzo).
    Ej.: «No, Obligación GB-1022-082» → «82» (último segmento numérico significativo).
    No sustituye la carpeta de crédito cuando esa carpeta existe explícitamente en SharePoint.
    """
    if not pdf_text or not pdf_text.strip():
        return None
    # Patrones explícitos primero (evitar NIT/cuentas largas sin contexto «obligación»)
    m = re.search(r"(?is)(?:obligaci[oó]n)\s*#\s*(\d{1,8})\b", pdf_text)
    if m:
        return str(int(m.group(1))) if m.group(1).isdigit() else m.group(1)
    m = re.search(r"(?is)\b(?:obligaci[oó]n)\s+(\d{1,8})\b(?!\s*\.?\d)", pdf_text)
    if m:
        return str(int(m.group(1))) if m.group(1).isdigit() else m.group(1)
    # No. / No, Obligacion GB-1022-082
    m = re.search(
        r"(?is)(?:no\.?\s*,?\s*)(?:obligaci[oó]n)\s+([a-z]{1,6}(?:-\d+)+)",
        pdf_text,
    )
    if m:
        parts = m.group(1).upper().split("-")
        tail = parts[-1]
        if tail.isdigit():
            return str(int(tail))
        return tail or None
    m = re.search(r"(?is)(?:obligaci[oó]n)\s+([a-z]{1,6}(?:-\d+)+)", pdf_text)
    if m:
        parts = m.group(1).upper().split("-")
        tail = parts[-1]
        if tail.isdigit():
            return str(int(tail))
        return tail or None
    # «No. Obligación: GB 1022-203» / «Obligación: GB-1022-203» / «Obligación: 265»
    m = re.search(
        r"(?i)obligaci[oó]n[ \t]*[:.][ \t]*"
        r"((?:[a-z]{1,6}[ \t\-]*)?\d{1,8}(?:[ \t]*-[ \t]*\d{1,8})*)(?![\d\-])",
        pdf_text,
    )
    if m:
        tail = re.findall(r"\d+", m.group(1))[-1]
        return str(int(tail))
    return None


def extract_credit_id_from_extract_pdf(pdf_bytes: bytes) -> str | None:
    text: str | None = None
    try:
        text = _read_pdf_text(pdf_bytes)
    except Exception:
        raw = pdf_bytes.decode(errors="ignore")
        if raw.startswith("PDF_MOCK:"):
            text = raw
        else:
            return None
    return extract_credit_id_from_extract_pdf_text(text or "")


def find_best_amortization_table(files: list[str], client_name: str, credit_id: str) -> str:
    """Localiza la tabla de amortización por nombre de archivo (sin parsear Excel).

    Contrato operador (fail-closed, barato en Generate con muchos créditos):

    - Solo cuentan Excel cuyo nombre indique *tabla* + *amortización*.
    - «Modelo de extracto» **no** sustituye a la tabla: se ignora.
    - 0 tablas → ``amortization_table_not_found``.
    - 2+ tablas → ``amortization_table_ambiguous`` (nunca desempatar por score).
    - 1 tabla (+ opcional modelo u otros archivos) → esa tabla.

    ``client_name`` / ``credit_id`` se conservan en la firma por compatibilidad
    con callers; no se usan para elegir entre varias tablas.
    """
    _ = client_name, credit_id
    tables: list[str] = []

    for f in files:
        if str(f).startswith("~$"):
            continue
        if not _is_amortization_excel_filename(f):
            continue
        f_norm = _normalize_str(f)
        if "tabla" in f_norm and "amortizacion" in f_norm:
            tables.append(f)

    if not tables:
        raise ValueError("amortization_table_not_found")
    if len(tables) > 1:
        raise ValueError("amortization_table_ambiguous")
    return tables[0]


def _read_pdf_text(pdf_bytes: bytes) -> str:
    """Extrae texto plano de un PDF. Lanza ValueError si el PDF no tiene texto."""
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore[no-redef]
        
    reader = PdfReader(BytesIO(pdf_bytes))
    text_parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text() or ""
        if t:
            text_parts.append(t)
    text = "\n".join(text_parts)
    
    if not text.strip():
        # Fallback a pdfplumber para PDFs con codificaciones de fuente complejas (ej. ERPs)
        try:
            import pdfplumber
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                fallback_parts = []
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    if t:
                        fallback_parts.append(t)
                text = "\n".join(fallback_parts)
        except Exception:
            pass
            
    if not text.strip():
        raise ValueError("pdf_no_text")
    return text


def extract_total_a_pagar_from_pdf(pdf_bytes: bytes) -> float:
    """
    Extrae el valor TOTAL A PAGAR de un PDF de extracto HBI.

    Soporta formatos latinos:
      - 18.826.879
      - 6.500.739
      - 1.234.567,89

    Lanza ValueError('extract_amount_not_found') si no puede parsear el monto.
    """
    text = _read_pdf_text(pdf_bytes)
    patterns = [
        r"TOTAL\s*A\s*PAGAR\s*[:\-\s]*\$?\s*([\d\.\,]+)",
        r"TOTAL\s*A\s*PAGAR\s*\$?\s*([\d\.\,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Formato latino: puntos = separadores de miles, coma = decimal
            # Ej: "18.826.879" -> 18826879, "1.234.567,89" -> 1234567.89
            if "," in raw:
                # Tiene decimal con coma
                raw = raw.replace(".", "").replace(",", ".")
            else:
                # Solo puntos como miles
                raw = raw.replace(".", "")
            try:
                return float(raw)
            except ValueError:
                pass
    raise ValueError("extract_amount_not_found")
