# U4-RC — Production readiness (plan)

## Objetivo

Release candidate técnicamente listo para producción, validado en sandbox,
**sin** deploy ni mutaciones de producción.

## HEAD de partida

- Código U4-UX: `57a9e46`
- Docs tip al inicio: `062726c` (solo documental tras código)
- Ambiente: sandbox
- Contabilidad productiva: deshabilitada (hostname vacío)
- Notify: destinatarios de prueba
- Mocks / Extract Index: off

## Bloqueantes

| ID | Tema | Estado |
|----|------|--------|
| B1 | FINALIZADO sin Notify → no DESCONOCIDO | Hecho (código) |
| B2 | Matriz EstadoProceso × jobs | Hecho (código + tests) |
| B3 | Multi-error Finalize extendido | Hecho (código + tests) |
| B4 | Axe página completa | Hecho (tests + fixes) |
| B5 | Responsive live sandbox | Pendiente deploy RC |
| B6 | Copy técnico solo en Detalles técnicos | En curso |
| B7 | Loading / polling | Auditoría en curso |
| B8 | E2E ambos bancos + errores | Pendiente |
| Prod RO | Overlay + paths-probe | Pendiente |
| ZIPs | sandbox + production-candidate | Pendiente |

## Fail-fast conservado (Finalize)

No se acumulan de forma segura (siguen fail-fast con ubicación/código):

- `review_has_open_errors` (hoja Errores)
- `review_schema_version_1_requires_regenerate`
- `duplicate_bank_amount_in_payment_group`
- Gates de control (`NO_READY_PROCESS`, `control_not_ready_for_finalize`, etc.)
- Resolución Graph (`credit_folder_*`, `missing_extract_route`, provisionamiento)
- Escrituras / O:P / idempotencia (no se tocan con errores bloqueantes)

Sí se acumulan: Estado/Validar Pago, intereses/mora/capital/otros, PAGO Y ABONO CAPITAL,
observaciones, totales, `amount_mismatch` por ID Pago, issues de Distribucion_Abonos
(ABONO CAPITAL / ABONO MORA) cuando son chequeos locales de hoja.

## Prohibido

Deploy producción, mutaciones prod, push, merge git, destinatarios reales.
