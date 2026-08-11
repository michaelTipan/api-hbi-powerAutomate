"""Fixtures sintéticos anonimizados de extractos (sin PII real)."""

# Familia: solo panel izquierdo (TOTAL A PAGAR), derecha vacía
EXTRACT_LEFT_ONLY = """
EXTRACTO DE CREDITO
No. Obligacion 258
Fecha limite de pago 23/05/2026
TOTAL A PAGAR $ 1.500.000
"""

# Familia: derecha = aplicacion anterior (NO es mora)
EXTRACT_RIGHT_APLICACION_ANTERIOR = """
EXTRACTO DE CREDITO
No. Obligacion 101
Fecha limite de pago 15/04/2026
TOTAL A PAGAR $ 2.200.000
Aplicacion anterior $ 800.000
Detalle del pago anterior cuota
"""

# Familia: derecha = saldo vencido / mora
EXTRACT_RIGHT_SALDO_VENCIDO = """
EXTRACTO DE CREDITO
No. Obligacion 77
Fecha limite de pago 10/03/2026
TOTAL A PAGAR $ 3.100.000
Saldo vencido $ 450.000
"""

# Familia: ambigua (ambos labels)
EXTRACT_RIGHT_AMBIGUO = """
EXTRACTO DE CREDITO
No. Obligacion 55
Fecha limite de pago 01/06/2026
TOTAL A PAGAR $ 900.000
Aplicacion anterior $ 100.000
Saldo vencido $ 200.000
"""

# Familia: derecha vacia explicita
EXTRACT_RIGHT_VACIO = """
EXTRACTO DE CREDITO
No. Obligacion 12
Fecha limite de pago 20/02/2026
TOTAL A PAGAR $ 750.000
"""
