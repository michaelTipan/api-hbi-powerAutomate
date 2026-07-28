"""
Genera PDFs de asiento contable estilo HBI a partir de la estructura
observada en los consolidados de muestra (página con No.Rad. / cuentas).
Salida: asientos_prueba/generados/
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(r"D:\CMC\HBI_Capital\asientos_prueba\generados")

# Asientos para créditos de la batería E2E sandbox
ASIENTOS = [
    {
        "filename": "Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 231.pdf",
        "voucher": "9001",
        "day": 27,
        "month": 7,
        "year": 2026,
        "nit": "900000231-1",
        "nombre": "GEOEXCON S.A.S",
        "credit": "231",
        "lines": [
            ("11100505", 19_000_171.00),
            ("13410519", 11_000_000.00),
            ("13430501", 7_500_000.00),
            ("41502030", 500_171.00),
        ],
    },
    {
        "filename": "Asiento 27-JUL-2026 PAGO Y ABONO CAPITAL GEOEXCON CRED 231.pdf",
        "voucher": "9002",
        "day": 27,
        "month": 7,
        "year": 2026,
        "nit": "900000231-1",
        "nombre": "GEOEXCON S.A.S",
        "credit": "231",
        "lines": [
            ("11100505", 24_000_171.00),
            ("13410519", 24_000_171.00),
        ],
    },
    {
        "filename": "Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 254.pdf",
        "voucher": "9003",
        "day": 23,
        "month": 2,
        "year": 2026,
        "nit": "900000231-1",
        "nombre": "GEOEXCON S.A.S",
        "credit": "254",
        "lines": [
            ("11100505", 6_514_755.00),
            ("13410519", 6_514_755.00),
        ],
    },
    {
        "filename": "Asiento 27-JUL-2026 PAGO CUOTA EQUINORTE CRED 258.pdf",
        "voucher": "9004",
        "day": 22,
        "month": 4,
        "year": 2026,
        "nit": "800000258-2",
        "nombre": "EQUINORTE S.A.S",
        "credit": "258",
        "lines": [
            ("11100505", 48_497_024.00),
            ("13410519", 28_000_000.00),
            ("13430501", 20_000_000.00),
            ("41502030", 497_024.00),
        ],
    },
    {
        "filename": "Asiento 27-JUL-2026 PAGO CUOTA EQUINORTE CRED 264.pdf",
        "voucher": "9005",
        "day": 15,
        "month": 4,
        "year": 2026,
        "nit": "800000258-2",
        "nombre": "EQUINORTE S.A.S",
        "credit": "264",
        "lines": [
            ("11100505", 32_691_683.00),
            ("13410519", 32_691_683.00),
        ],
    },
    {
        "filename": "Asiento 27-JUL-2026 ABONO CAPITAL EQUINORTE CRED 265.pdf",
        "voucher": "9006",
        "day": 27,
        "month": 7,
        "year": 2026,
        "nit": "800000258-2",
        "nombre": "EQUINORTE S.A.S",
        "credit": "265",
        "lines": [
            ("11100505", 500_000.00),
            ("13410519", 500_000.00),
        ],
    },
    {
        "filename": "Asiento 27-JUL-2026 ABONO MORA EQUINORTE CRED 265.pdf",
        "voucher": "9007",
        "day": 27,
        "month": 7,
        "year": 2026,
        "nit": "800000258-2",
        "nombre": "EQUINORTE S.A.S",
        "credit": "265",
        "lines": [
            ("11100505", 200_000.00),
            ("13410519", 200_000.00),
        ],
    },
    {
        "filename": "Asiento 27-JUL-2026 PAGO CUOTA AGRECAR CRED 37.pdf",
        "voucher": "9008",
        "day": 27,
        "month": 7,
        "year": 2026,
        "nit": "900000037-3",
        "nombre": "AGRECAR S.A.S",
        "credit": "37",
        "lines": [
            ("11100505", 25_075_203.00),
            ("13410519", 15_000_000.00),
            ("13430501", 10_000_000.00),
            ("41502030", 75_203.00),
        ],
    },
]


def _money(v: float) -> str:
    # Estilo muestra: 19,000,171.00
    return f"{v:,.2f}"


def draw_asiento(path: Path, data: dict) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 20 * mm

    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, data["voucher"])
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, "Año       Mes      Día")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"{data['year']}  {data['month']}  {data['day']}")
    c.drawRightString(width - 20 * mm, y, "Fecha  : SIN ENTIDAD")
    y -= 6 * mm
    c.drawString(20 * mm, y, "Entidad : 0   Soporte :")
    y -= 10 * mm

    c.drawString(20 * mm, y, f"N° Identificación : {data['nit']}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Nombre : {data['nombre']}")
    y -= 12 * mm

    # El parser exige monto + "PAGO: … Linea 544 1 {cuenta}" en la MISMA línea
    # (como los asientos reales de HBI). Separar el monto en otra línea falla el parseo.
    total = sum(v for _, v in data["lines"])
    for cuenta, valor in data["lines"]:
        line = f"{_money(valor)} PAGO: No.Rad. {data['credit']} Linea 544 1 {cuenta}"
        c.drawString(20 * mm, y, line)
        y -= 6 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, f"{_money(total)}  {_money(total)}")
    y -= 16 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, "PATRICIA  BELLOS PEDRAZA")
    y -= 8 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        20 * mm,
        y,
        "Asiento de prueba E2E sandbox — estructura basada en consolidados HBI",
    )
    c.showPage()
    c.save()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for item in ASIENTOS:
        dest = OUT / item["filename"]
        draw_asiento(dest, item)
        print("OK", dest.name)
    print(f"Total: {len(ASIENTOS)} en {OUT}")


if __name__ == "__main__":
    main()
