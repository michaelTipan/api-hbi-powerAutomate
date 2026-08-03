# Guía para colaboradores — sandbox (entorno de pruebas)

Documentación para quien mejora la UI **sin tocar producción**.

| Documento | Para qué |
|---|---|
| [SANDBOX_DEPLOY.md](./SANDBOX_DEPLOY.md) | Cómo empaquetar y desplegar solo a pruebas |
| [../release/MANUAL_PRUEBAS_UI_SANDBOX.md](../release/MANUAL_PRUEBAS_UI_SANDBOX.md) | Cómo probar manualmente el flujo operador en la UI |
| [../release/MANUAL_USUARIO_UI.md](../release/MANUAL_USUARIO_UI.md) | Manual de uso (qué hace cada pantalla) |
| [../release/ACCESO_OPERADOR_SANDBOX.md](../release/ACCESO_OPERADOR_SANDBOX.md) | URL y usuario sandbox (sin contraseña) |

## Rama recomendada

Trabajar sobre la rama de UI (p. ej. `feat/ui-in-app-review-and-asientos` o la que te indiquen).  
La base estable previa a R0–R3 fue `integration/performance-and-ui`.

## Regla de oro

1. **Sandbox = rutas COMWARE PRUEBAS** en SharePoint.  
2. **Nunca** despliegues con overlay `production` ni rutas productivas.  
3. Antes de cualquier deploy: `.\scripts\switch-env.ps1 -Status` y confirma `ACTIVE_ENVIRONMENT=sandbox` y path `…/03 COMWARE PRUEBAS-…`.
