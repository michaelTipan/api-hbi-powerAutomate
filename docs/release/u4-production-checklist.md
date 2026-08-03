# U4 Production Checklist

- [x] Suite pytest completa (1301 passed / 1 skipped)
- [x] Suite frontend (56) + tsc + build
- [x] E2E Bogotá Generate→Amortización
- [x] Bancolombia Notify + already_notified
- [x] Errores recuperables / API (9/9 live + fixtures)
- [x] Responsive live (61/61)
- [x] Axe automatizado (previo U4-RC)
- [x] Deploy `.env` rm verificado (2 deploys)
- [x] ZIP sandbox final + SHA + deploy sandbox
- [x] Overlay production estático OK
- [x] Overlay `production-ui-enabled` (UI ON + paths prod + smoke off)
- [x] Paths-probe production read-only live (tras deploy UI prod)
- [x] ZIP production-candidate creado (**histórico**; sustituir por build UI prod)
- [x] Diff código sandbox/prod idéntico (solo `.env` / overlay)
- [x] SPA sin secretos (API key / Graph secret / password)
- [x] Rollback documentado (`docs/release/u4-rollback-plan.md`)
- [x] App Service live confirmado post-deploy UI prod (health + bootstrap + paths-probe)
- [x] Deploy producción UI opt-in **autorizado** (GO parcial)
- [x] Push/merge: no ejecutados
- [x] Mutaciones productivas intencionales: cero en paths-probe RO (smoke accounting off)

## Go / No-go

**GO parcial (UI prod opt-in)** cuando:

1. `ACTIVE_ENVIRONMENT=production`, clients base **sin** PRUEBAS,
2. `UI_ENABLED=true` + `local_session` válido + writes/flags ON,
3. health + bootstrap + paths-probe RO verdes,
4. operador consciente: escrituras UI tocan **clientes reales**.

**NO-GO total** si paths-probe falla, health no muestra production+ui, o smoke Contabilidad queda encendido.
