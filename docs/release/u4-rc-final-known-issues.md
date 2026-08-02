# U4-RC — Known issues (no bloqueantes)

Estos puntos **no invalidan** la aceptación completa del flujo Banco Bogotá en sandbox.

## 1. Bancolombia

- Existe proceso histórico en `PENDIENTE_ASIENTOS`.
- Solo se ejecutó smoke parcial.
- No se completó un segundo E2E bancolombia.
- **No afecta** la aceptación Bogotá (`0877507c-8005-4c60-bfa1-d04f241a40ca`).

## 2. Accesibilidad

- Hay pruebas frontend existentes en el repo.
- **axe formal live** no se ejecutó en R3.
- Pendiente opcional post-entrega; no bloquea cierre sandbox.

## 3. Producción

- Producción **no** desplegada.
- Producción **no** autorizada.
- **No** forma parte de esta entrega sandbox.

## 4. Worker

- Un solo worker en App Service.
- Procesos largos pueden afectar el polling de la UI.
- Mitigación operativa: evitar campañas concurrentes pesadas en demo.

## 5. Credenciales

- Contraseña de `operador_hbi` entregada por **canal seguro**.
- **No** almacenada en Git, Markdown, JSON de release, logs ni capturas.
- Rotación adicional **no** forma parte de R4.
