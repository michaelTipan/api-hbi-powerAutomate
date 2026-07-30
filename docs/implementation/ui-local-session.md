# Autenticación UI local_session (D2-LS1)

## Contexto

El operador **no** administra App Registrations Entra. Por eso el modo operativo
es `UI_AUTH_MODE=local_session`. `entra` permanece implementado para una
migración futura; `mock` solo para desarrollo local (prohibido en Azure).

## Separación

| Superficie | Auth |
|---|---|
| `/graph/*` | `X-API-Key` (Power Automate) |
| `/api/ui/v1/*` | cookie de sesión `__Host-hbi_session` (o Bearer Entra futuro) |
| `/app/*` | SPA; datos vía sesión |
| `/health` | público |

El navegador **nunca** recibe `API_HTTP_KEY` ni secretos Graph.

## Sesión

- Token opaco ≥32 bytes, solo en cookie HttpOnly/Secure/SameSite=Strict/Path=/ sin Domain.
- En memoria se guarda **SHA-256(token)**, no el token.
- TTL absoluto + idle; reinicio del App Service invalida sesiones (1 worker).
- `SessionRepository` permite migrar a store compartido si hay escala horizontal.

## Password hash

```
pbkdf2_sha256$600000$<salt_b64>$<digest_b64>
```

Generar (interactivo, no escribe `.env`):

```powershell
python .\scripts\generate-ui-password-hash.py
```

Copiar la salida a `UI_LOCAL_PASSWORD_HASH` en `api-hbi-powerAutomate.env`
junto con `UI_LOCAL_USERNAME`. **Nunca** en Git.

## CSRF (fase write futura)

La sesión ya genera `csrf_token`. Diseño previsto:

- endpoint protegido para leer CSRF;
- header `X-CSRF-Token` en POST;
- comparación constant-time + Origin + SameSite;
- rotación en login / invalidación en logout.

D2-LS1 no habilita POST operativos.

## Fail-closed

Con `UI_ENABLED=true` y `local_session`, la UI no monta si faltan usuario/hash,
el hash es inválido/inseguro, cookies inseguras en Azure, o el ambiente no es
sandbox (restricción D2).
