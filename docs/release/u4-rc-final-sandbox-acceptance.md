# U4-RC — Aceptación final sandbox

**Estado:** U4-RC SANDBOX FUNCIONAL COMPLETO + **hotfix CSRF R3.1** (2026-08-01)

## Checklist entrega

- [x] UI enabled en Azure sandbox
- [x] Login `operador_hbi`
- [x] Dashboard / procesos
- [x] Generate / Finalize / Notify / Merge / Amortización (Bogotá)
- [x] Errores múltiples Finalize + persistencia
- [x] Idempotencia (409 busy / already_*)
- [x] Rutas PRUEBAS + Contabilidad disabled
- [x] pytest + frontend + tsc + build
- [x] **R3.1 CSRF hotfix** (`index-BAxcI8BG.js`, build `…-csrf-1e75f03`)
- [ ] Bancolombia E2E completo (smoke parcial; proceso histórico PENDIENTE_ASIENTOS)
- [ ] Deploy producción (no autorizado)

## Artefactos

- Evidencia E2E R3: `D:\CMC\HBI_Capital\_work\u4_rc_enabled_e2e\`
- Evidencia CSRF R3.1: `D:\CMC\HBI_Capital\_work\u4_rc_csrf_hotfix\`
- Implementación R3: `docs/implementation/u4-rc-r3-sandbox-enabled-e2e.md`
- Implementación R3.1: `docs/implementation/u4-rc-r3-1-csrf-hotfix.md`
- ZIP CSRF SHA: `834A13F83A7BEAD49D51A39BD144ACE7C0335CBF8F14ACA71019C1A1D6AF1883`
- Build live: `u4-rc-sandbox-ui-enabled-csrf-1e75f03`
- Bundle live: `index-BAxcI8BG.js`

## No hacer

- Push/merge sin revisión
- production-candidate
- Contabilidad productiva
- Correos a destinatarios reales corporativos
