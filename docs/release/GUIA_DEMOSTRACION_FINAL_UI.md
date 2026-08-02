# Guía de demostración final — UI HBI Capital (sandbox)

Demostrar el sistema **sin ejecutar otro proceso financiero**.

**URL:** `https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net/app/`  
**Usuario:** `operador_hbi`  
**Entorno:** SANDBOX / PRUEBAS  
**Contraseña:** entregada por canal seguro (no está en este documento).

## Prohibido durante la demo

No pulsar nuevamente:

- Generate
- Finalize
- Notify
- Merge
- Procesar amortización

Toda la demo es lectura + navegación sobre procesos ya ejecutados.

## Secuencia recomendada

1. Abrir `/app/`.
2. Iniciar sesión con `operador_hbi`.
3. Mostrar el indicador **SANDBOX / PRUEBAS**.
4. Mostrar el dashboard.
5. Mostrar **Banco Bogotá** completado (estado terminal / progreso completo).
6. Abrir el detalle del ProcessKey:
   `payment-validation|banco_bogota|2026-08-01|0877507c-8005-4c60-bfa1-d04f241a40ca`
7. Mostrar progreso completo (pasos Generate → Finalize → Notify → Merge → Amortización).
8. Mostrar documentos asociados.
9. Mostrar historial de intentos / jobs.
10. Mostrar idempotencias (reintentos previos responden 409 busy / already_* — solo explicar; no re-disparar).
11. Mostrar caso multi-error (si sigue visible):
    ProcessKey con UUID `b3dc9d29-c6ba-4b3f-80c7-1e1be636a168`
12. Mostrar la sección **Requieren atención**.
13. Mostrar detalles técnicos plegables.
14. Mostrar responsive (ventana estrecha / móvil).
15. Mostrar login/logout.
16. Explicar que **Contabilidad está deshabilitada**.
17. Explicar que todo opera dentro de **COMWARE PRUEBAS**.

## Mensajes clave para stakeholders

- El flujo Bogotá de aceptación está **COMPLETADO / AMORTIZACION_APLICADA**.
- Notify usa destinatario **sandbox**, no correo productivo.
- No hay deploy ni autorización de producción en esta entrega.
- Pendientes (Bancolombia parcial, axe formal, worker único) no invalidan la aceptación Bogotá.
