# Manual de pruebas manuales — UI operador (sandbox)

Guía paso a paso para **probar a mano** la UI de validación de pagos en el entorno de pruebas. Pensada para alguien que no ha ejecutado el flujo antes.

## Antes de empezar

1. Lee [ACCESO_OPERADOR_SANDBOX.md](./ACCESO_OPERADOR_SANDBOX.md) (URL + usuario).
2. Confirma que el badge de la app diga **ENTORNO DE VALIDACIÓN** / sandbox.
3. Trabaja **solo** sobre bancos/archivos de **COMWARE PRUEBAS** en SharePoint.
4. Excepción de SharePoint: el **Excel inicial del banco** (`BANCO_BANCOLOMBIA.xlsx` / `BANCO_BOGOTA.xlsx`) se edita en SharePoint. El resto del flujo (revisión, asientos, finalize, notify, merge, amortización) debe poder hacerse **desde la UI**.

### Material de prueba típico

| Qué | Dónde |
|---|---|
| Excel del banco | SharePoint → `…/01 CARGA TRANSACCIONES BANCO/` |
| Destinatarios correo | `…/02 CONTROL OPERATIVO/CORREOS.xlsx` (sandbox) |
| PDF de asientos | Archivos de prueba del equipo (PDF válido por pago/crédito) |

Si no tienes un lote de prueba, pide al dueño del entorno un Excel de banco ya preparado en PRUEBAS.

---

## Checklist rápido (smoke)

Tras un deploy o al empezar el día:

- [ ] Login con `operador_hbi` OK  
- [ ] Badge sandbox visible  
- [ ] Panel carga bancos (Bogotá / Bancolombia)  
- [ ] Tras Generate, el mensaje **no** te obliga a abrir Excel de revisión en SharePoint para editar (debe apuntar a la UI)  
- [ ] En detalle, fase «Finalizar revisión»: aparece **Revisión del lote**  
- [ ] En fase Merge: aparece **Cargar asientos** (lista y/o carga manual)

---

## Flujo completo (1 banco, 1 día)

Ejemplo con **Bancolombia**. Sustituye por Bogotá si aplica.

### 0. Preparar Excel del banco (única parte en SharePoint)

1. Abre el archivo del banco en SharePoint (botón **Abrir archivo del banco** en el Panel, o ruta de carga).
2. Completa las filas que falten (conceptos, montos, etc.) según el caso de prueba.
3. Guarda y cierra Excel Online.
4. Vuelve a la UI (`/app/`).

### 1. Iniciar validación (Generate)

1. En **Panel → Nuevo proceso**, elige el banco.
2. Pulsa **Iniciar validación**.
3. Espera el seguimiento hasta estado completado / proceso activo.
4. En **Procesos activos**, abre el proceso (**Continuar proceso** / tarjeta).

**Esperado:** fase actual = Finalizar revisión; mensaje de estado apunta a validar en la UI.

### 2. Revisar y editar en la UI (R0–R1)

1. Bajo el CTA de fase debe verse el panel **Revisión del lote**.
2. Edita montos / estado pago / validar pago según el caso.
3. **Guardar cambios** si editas (borradores incompletos OK).
4. Opcional: **Comprobar antes de finalizar** (preflight).
5. No deberías necesitar «Abrir archivo de revisión» para completar la distribución.

**Esperado:** filas editables; guardado sin error; preflight muestra OK o lista de problemas.

### 3. Finalizar revisión (R2)

1. En la fase, pulsa **Finalizar revisión**.
2. Confirma el diálogo.
3. Espera el job (banner / actualización).

**Esperado:** avanza a fase Enviar correo (o estado equivalente). Si falla, lee el mensaje en la UI y no reintentes a ciegas.

### 4. Enviar correo (Notify)

1. Pulsa **Enviar correo**.
2. Confirma.

**Esperado:** correo a destinatarios de `CORREOS.xlsx` de PRUEBAS (no producción). Fase avanza a Generar PDF consolidado / Esperando soportes.

### 5. Cargar asientos (R3)

1. En fase Merge / «Esperando documentos contables», usa **Cargar asientos**.
2. Si hay pendientes listados: **Elegir PDF** por cada pago/crédito.
3. Si no hay lista: usa **Carga manual** (id pago + crédito + PDF).
4. Actualiza el detalle (icono ↻) hasta que el consolidado esté habilitado.

**Esperado:** no dependes de abrir «Carpeta ASIENTOS» en SharePoint para cargar. El botón **Generar PDF consolidado** se habilita cuando los grupos están listos.

### 6. Generar PDF consolidado (Merge)

1. Pulsa **Generar PDF consolidado**.
2. Espera el job.

**Esperado:** fase Amortización / Listo para amortización.

### 7. Procesar amortización

1. Pulsa **Procesar amortización**.
2. Espera hasta **Proceso completado**.

**Esperado:** 5/5 fases en verde; sin acciones pendientes.

---

## Qué anotar si algo falla

Copia y envía al equipo:

1. URL exacta (panel o detalle).  
2. Banco + fecha del proceso.  
3. Texto del badge de estado.  
4. Mensaje de error / job (si aparece).  
5. Resultado de `GET /health` (`build`, `environment`) — opcional, ayuda a saber la versión.  
6. Captura de pantalla.

---

## Pruebas que NO debes hacer en sandbox sin acuerdo

- Cambiar rutas a clientes productivos.  
- Usar destinatarios reales de producción en `CORREOS.xlsx`.  
- Disparar el mismo Generate muchas veces “por si acaso” sin mirar procesos activos.  
- Deploy a producción.

---

## Relacionado

- Uso de pantallas: [MANUAL_USUARIO_UI.md](./MANUAL_USUARIO_UI.md)  
- Deploy: [../contributor/SANDBOX_DEPLOY.md](../contributor/SANDBOX_DEPLOY.md)  
- Demo solo lectura (sin disparar jobs): [GUIA_DEMOSTRACION_FINAL_UI.md](./GUIA_DEMOSTRACION_FINAL_UI.md)
