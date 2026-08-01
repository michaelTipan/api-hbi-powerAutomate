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
- [ ] Paths-probe production read-only en runtime aislado
- [x] ZIP production-candidate creado (**no desplegado**)
- [x] Diff código sandbox/prod idéntico (solo `.env`)
- [x] SPA sin secretos
- [x] Rollback documentado (`docs/release/u4-rollback-plan.md`)
- [ ] Deploy producción autorizado
- [x] Push/merge: no ejecutados
- [x] Producción mutada: cero (App Service permanece sandbox)

## Go / No-go

**NO-GO** hasta paths-probe productivo RO aislado verde.
