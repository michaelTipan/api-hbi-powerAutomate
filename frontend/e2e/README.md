# Playwright E2E — UI simulada (operador)

Harness **v1 ui-simulated**: la SPA se sirve con `vite preview` y todas las
llamadas `GET/POST /api/ui/v1/*` se interceptan con `page.route` (sin sandbox
real ni SharePoint).

Documentación quirúrgica completa:
[`../../docs/e2e/OPERATOR_E2E_REPORT.md`](../../docs/e2e/OPERATOR_E2E_REPORT.md)

## Comandos

```powershell
cd D:\CMC\HBI_Capital\wt-ui-stable\frontend
npm run test:e2e
npm run test:e2e -- --headed
npm run test:e2e -- e2e/tests/ui-simulated/p0-login.spec.ts
```

Traces en fallo: `frontend/e2e/test-results/` y reporte HTML en
`frontend/playwright-report/`.
