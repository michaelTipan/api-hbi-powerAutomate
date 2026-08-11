"""Fixtures sintéticos anonimizados de extractos (sin PII real).

Usar marcadores ---LEFT--- / ---RIGHT--- para tests espaciales.
Texto plano sin marcadores → fallback lineal conservador.
"""

# 1) izquierda normal + derecha vacía
EXTRACT_LEFT_ONLY = """
---LEFT---
EXTRACTO DE CREDITO
No. Obligacion 258
Fecha limite de pago 23/05/2026
TOTAL A PAGAR $ 1.500.000
---RIGHT---
"""

# 2) izquierda con «Intereses de mora», derecha vacía → NO es saldo vencido
EXTRACT_LEFT_INTERESES_MORA_RIGHT_EMPTY = """
---LEFT---
EXTRACTO DE CREDITO
No. Obligacion 258
Fecha limite de pago 23/05/2026
TOTAL A PAGAR $ 1.500.000
Intereses de mora $ 45.000
---RIGHT---
"""

# 3-7) familias mora panel derecho
EXTRACT_RIGHT_SALDO_MORA = """
---LEFT---
No. Obligacion 77
Fecha limite de pago 10/03/2026
TOTAL A PAGAR $ 3.100.000
---RIGHT---
SALDO MORA $ 13.075.842
"""

EXTRACT_RIGHT_CUOTA_MORA = """
---LEFT---
No. Obligacion 77
Fecha limite de pago 10/03/2026
TOTAL A PAGAR $ 3.100.000
---RIGHT---
CUOTA MORA / MARZO $ 450.000
"""

EXTRACT_RIGHT_CUOTAS_EN_MORA = """
---LEFT---
No. Obligacion 77
Fecha limite de pago 10/03/2026
TOTAL A PAGAR $ 2.000.000
---RIGHT---
CUOTAS EN MORA $ 800.000
"""

EXTRACT_RIGHT_SALDO_EN_MORA = """
---LEFT---
No. Obligacion 77
Fecha limite de pago 10/03/2026
TOTAL A PAGAR $ 2.000.000
---RIGHT---
SALDO EN MORA $ 900.000
"""

EXTRACT_RIGHT_TOTAL_EN_MORA = """
---LEFT---
No. Obligacion 77
Fecha limite de pago 10/03/2026
TOTAL A PAGAR $ 2.000.000
---RIGHT---
TOTAL EN MORA $ 1.100.000
"""

EXTRACT_RIGHT_SALDO_VENCIDO = """
---LEFT---
EXTRACTO DE CREDITO
No. Obligacion 77
Fecha limite de pago 10/03/2026
TOTAL A PAGAR $ 3.100.000
---RIGHT---
Saldo vencido $ 450.000
"""

# 8-13) aplicación anterior / pagado
EXTRACT_RIGHT_APLICACION_ANTERIOR = """
---LEFT---
EXTRACTO DE CREDITO
No. Obligacion 101
Fecha limite de pago 15/04/2026
TOTAL A PAGAR $ 2.200.000
---RIGHT---
Aplicacion anterior $ 800.000
Detalle del pago anterior cuota
"""

EXTRACT_RIGHT_APLICACION_CUOTA_ABONO = """
---LEFT---
No. Obligacion 101
Fecha limite de pago 15/04/2026
TOTAL A PAGAR $ 2.200.000
---RIGHT---
APLICACION DE PAGO CUOTA Y ABONO $ 950.000
"""

EXTRACT_RIGHT_APLICACION_ABONO_CAPITAL = """
---LEFT---
No. Obligacion 101
Fecha limite de pago 15/04/2026
TOTAL A PAGAR $ 2.200.000
---RIGHT---
APLICACION ABONO CAPITAL $ 500.000
"""

EXTRACT_RIGHT_TOTAL_PAGADO = """
---LEFT---
No. Obligacion 101
Fecha limite de pago 15/04/2026
TOTAL A PAGAR $ 2.200.000
---RIGHT---
TOTAL PAGADO $ 1.200.000
"""

EXTRACT_RIGHT_TOTAL_APLICADO = """
---LEFT---
No. Obligacion 101
Fecha limite de pago 15/04/2026
TOTAL A PAGAR $ 2.200.000
---RIGHT---
TOTAL APLICADO $ 1.200.000
"""

EXTRACT_RIGHT_VALOR_PAGADO = """
---LEFT---
No. Obligacion 101
Fecha limite de pago 15/04/2026
TOTAL A PAGAR $ 2.200.000
---RIGHT---
VALOR PAGADO $ 1.200.000
"""

# 14) ambigua
EXTRACT_RIGHT_AMBIGUO = """
---LEFT---
EXTRACTO DE CREDITO
No. Obligacion 55
Fecha limite de pago 01/06/2026
TOTAL A PAGAR $ 900.000
---RIGHT---
Aplicacion anterior $ 100.000
Saldo vencido $ 200.000
"""

EXTRACT_RIGHT_VACIO = """
---LEFT---
EXTRACTO DE CREDITO
No. Obligacion 12
Fecha limite de pago 20/02/2026
TOTAL A PAGAR $ 750.000
---RIGHT---
"""

# 15-16) sin fecha / sin crédito
EXTRACT_NO_FECHA = """
---LEFT---
No. Obligacion 12
TOTAL A PAGAR $ 750.000
---RIGHT---
"""

EXTRACT_NO_CREDITO = """
---LEFT---
Fecha limite de pago 20/02/2026
TOTAL A PAGAR $ 750.000
---RIGHT---
"""

# 17) variantes crédito
EXTRACT_CREDITO_GB_DASH = """
---LEFT---
No. Obligacion GB-1022-209
Fecha limite de pago 20/02/2026
TOTAL A PAGAR $ 100.000
---RIGHT---
"""

EXTRACT_CREDITO_GB_SPACE = """
---LEFT---
No. Obligacion GB 1022-209
Fecha limite de pago 20/02/2026
TOTAL A PAGAR $ 100.000
---RIGHT---
"""

EXTRACT_CREDITO_GB_COMPACT = """
---LEFT---
No. Obligacion GB1022-209
Fecha limite de pago 20/02/2026
TOTAL A PAGAR $ 100.000
---RIGHT---
"""

EXTRACT_CREDITO_GB_OBLIGACION = """
---LEFT---
No. Obligación GB 1022-057
Fecha limite de pago 20/02/2026
TOTAL A PAGAR $ 100.000
---RIGHT---
"""

# Mock espacial con spans (page width ~200; threshold 55% → 110)
# LEFT x<110, RIGHT x>=110
PDF_MOCK_SPATIAL_INTERESES_LEFT = """PDF_MOCK_SPATIAL:
SPAN|10|90|700|712|No. Obligacion 258
SPAN|10|90|680|692|Fecha limite de pago 23/05/2026
SPAN|10|90|660|672|TOTAL A PAGAR $ 1.500.000
SPAN|10|90|640|652|Intereses de mora $ 45.000
SPAN|120|190|700|712|
"""

PDF_MOCK_SPATIAL_SALDO_MORA_RIGHT = """PDF_MOCK_SPATIAL:
SPAN|10|90|700|712|No. Obligacion 77
SPAN|10|90|680|692|Fecha limite de pago 10/03/2026
SPAN|10|90|660|672|TOTAL A PAGAR $ 3.100.000
SPAN|120|190|700|712|SALDO MORA $ 13.075.842
"""
