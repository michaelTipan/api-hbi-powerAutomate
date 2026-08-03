import { useEffect, useRef, useState } from "react";
import {
  fetchProcessReview,
  patchProcessReview,
  postProcessReviewPreflight,
} from "../api/client";
import { UiApiError } from "../api/errors";
import { operatorErrorMessage } from "../domain/jobMessages";
import type {
  UiLink,
  UiReviewAbonoRow,
  UiReviewErrorItem,
  UiReviewPagoRow,
  UiReviewPreflightIssue,
  UiReviewResponse,
  UiReviewRowPatch,
} from "../types/contract";

type DraftFields = Record<string, string>;
type DraftMap = Record<string, DraftFields>;

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("es-CO", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function moneyInputValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return String(value);
}

function RowLinks({ links }: { links: readonly UiLink[] }) {
  if (!links.length) return <span className="meta">—</span>;
  return (
    <span className="review-read-links">
      {links.map((l) =>
        l.web_url ? (
          <a
            key={`${l.rel}-${l.web_url}`}
            className="text-link"
            href={l.web_url}
            target="_blank"
            rel="noreferrer"
          >
            {l.rel === "extract"
              ? "Extracto"
              : l.rel === "folder"
                ? "Carpeta"
                : l.rel === "tabla"
                  ? "Tabla"
                  : l.label}
          </a>
        ) : (
          <span key={`${l.rel}-${l.label}`} className="meta">
            {l.label}
          </span>
        ),
      )}
    </span>
  );
}

function fieldValue(
  drafts: DraftMap,
  rowKey: string,
  field: string,
  fallback: string | number | null | undefined,
): string {
  const draft = drafts[rowKey]?.[field];
  if (draft !== undefined) return draft;
  if (fallback === null || fallback === undefined) return "";
  return String(fallback);
}

function buildChanges(drafts: DraftMap): UiReviewRowPatch[] {
  const out: UiReviewRowPatch[] = [];
  for (const [row_key, fields] of Object.entries(drafts)) {
    const mapped: Record<string, string | number | null> = {};
    for (const [k, raw] of Object.entries(fields)) {
      const trimmed = raw.trim();
      if (
        k === "aplicar_a_extracto" ||
        k === "mora_a_aplicar" ||
        k === "abono_a_capital" ||
        k === "otros_valores"
      ) {
        if (trimmed === "") {
          mapped[k] = null;
        } else {
          const n = Number(trimmed.replace(",", "."));
          mapped[k] = Number.isFinite(n) ? n : trimmed;
        }
      } else {
        mapped[k] = trimmed;
      }
    }
    if (Object.keys(mapped).length > 0) {
      out.push({ row_key, fields: mapped });
    }
  }
  return out;
}

/**
 * Panel de revisión: R0 lectura; R1 edición si editEnabled.
 */
export function ReviewReadPanel({
  processKey,
  enabled,
  editEnabled = false,
  onNavigateToCredit,
}: {
  processKey: string;
  enabled: boolean;
  editEnabled?: boolean;
  onNavigateToCredit?: (credito: string) => void;
}) {
  const [review, setReview] = useState<UiReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightIssues, setPreflightIssues] = useState<UiReviewPreflightIssue[]>(
    [],
  );
  const [tab, setTab] = useState<"pagos" | "abonos">("pagos");
  const [highlightKey, setHighlightKey] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftMap>({});
  const rowRefs = useRef<Record<string, HTMLTableRowElement | null>>({});

  const dirty = Object.keys(drafts).length > 0;
  const canEdit = Boolean(editEnabled && review && !review.read_only);

  async function reloadReview() {
    const data = await fetchProcessReview(processKey);
    setReview(data);
    setDrafts({});
    return data;
  }

  useEffect(() => {
    if (!enabled || !processKey) {
      setReview(null);
      setError(null);
      setDrafts({});
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      setInfo(null);
      setPreflightIssues([]);
      try {
        const data = await fetchProcessReview(processKey);
        if (!cancelled) {
          setReview(data);
          setDrafts({});
        }
      } catch (e) {
        if (!cancelled) {
          setReview(null);
          setError(
            operatorErrorMessage(e, "No pudimos cargar la revisión.").message,
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, processKey]);

  function setDraftField(rowKey: string, field: string, value: string) {
    setDrafts((prev) => ({
      ...prev,
      [rowKey]: { ...(prev[rowKey] || {}), [field]: value },
    }));
    setInfo(null);
  }

  function goToCredit(credito: string, preferPago = true) {
    const c = credito.trim();
    if (!c || !review) return;
    onNavigateToCredit?.(c);
    const inPagos = review.pagos.find((p) => p.credito.trim() === c);
    const inAbonos = review.abonos.find((a) => a.credito.trim() === c);
    if (preferPago && inPagos) {
      setTab("pagos");
      setHighlightKey(inPagos.row_key);
      queueMicrotask(() => {
        rowRefs.current[inPagos.row_key]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      });
      return;
    }
    if (inAbonos) {
      setTab("abonos");
      setHighlightKey(inAbonos.row_key);
      queueMicrotask(() => {
        rowRefs.current[inAbonos.row_key]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      });
      return;
    }
    if (inPagos) {
      setTab("pagos");
      setHighlightKey(inPagos.row_key);
      queueMicrotask(() => {
        rowRefs.current[inPagos.row_key]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      });
    }
  }

  async function onSave() {
    if (!review?.etag || !dirty) return;
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const res = await patchProcessReview(
        processKey,
        buildChanges(drafts),
        review.etag,
      );
      setReview(res.review);
      setDrafts({});
      setInfo("Cambios guardados en el Excel de revisión.");
      setPreflightIssues([]);
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos guardar la revisión.");
      setError(msg.message);
      if (e instanceof UiApiError && e.errorCode === "review_etag_conflict") {
        try {
          await reloadReview();
          setInfo(
            "El archivo cambió en SharePoint. Recargamos la revisión; vuelva a aplicar sus cambios.",
          );
        } catch {
          /* keep error */
        }
      }
    } finally {
      setSaving(false);
    }
  }

  async function onPreflight() {
    setPreflightBusy(true);
    setError(null);
    setInfo(null);
    try {
      const res = await postProcessReviewPreflight(processKey);
      setPreflightIssues(res.issues);
      if (res.ok) {
        setInfo("Preflight OK: el lote cumple las reglas de Finalizar.");
      } else {
        setInfo(
          `Preflight encontró ${res.issue_count} problema(s). Puede seguir guardando borradores.`,
        );
      }
    } catch (e) {
      setError(
        operatorErrorMessage(e, "No pudimos ejecutar el preflight.").message,
      );
    } finally {
      setPreflightBusy(false);
    }
  }

  if (!enabled) return null;

  return (
    <section className="panel" id="review-read-panel" aria-labelledby="review-read-title">
      <h2 id="review-read-title" className="section-title">
        Revisión del lote
      </h2>
      <p className="meta" style={{ marginTop: 0 }}>
        {canEdit
          ? "Edite montos, validación y observaciones aquí. Guardar permite borradores incompletos; Finalizar (fase siguiente) exige cuadre completo."
          : "Solo lectura. Active UI_REVIEW_EDIT_ENABLED en sandbox para editar desde la UI."}
      </p>

      {loading ? <p className="meta">Cargando revisión…</p> : null}
      {error ? <div className="error-box">{error}</div> : null}
      {info ? <div className="review-read-info">{info}</div> : null}

      {canEdit && dirty ? (
        <div className="review-read-dirty" role="status">
          Hay cambios sin guardar.
        </div>
      ) : null}

      {canEdit ? (
        <div className="review-read-actions">
          <button
            type="button"
            className="btn"
            disabled={!dirty || saving || !review?.etag}
            onClick={() => void onSave()}
          >
            {saving ? "Guardando…" : "Guardar cambios"}
          </button>
          <button
            type="button"
            className="btn secondary"
            disabled={preflightBusy || dirty}
            title={
              dirty
                ? "Guarde los cambios antes de ejecutar el preflight"
                : undefined
            }
            onClick={() => void onPreflight()}
          >
            {preflightBusy ? "Validando…" : "Comprobar antes de finalizar"}
          </button>
          {dirty ? (
            <button
              type="button"
              className="btn secondary"
              disabled={saving}
              onClick={() => {
                setDrafts({});
                setInfo(null);
              }}
            >
              Descartar cambios
            </button>
          ) : null}
        </div>
      ) : null}

      {preflightIssues.length > 0 ? (
        <div className="review-read-preflight" role="region" aria-label="Resultado preflight">
          <h3 className="phase-docs-title">Problemas detectados (preflight)</h3>
          <ul className="review-read-error-list">
            {preflightIssues.map((issue, idx) => (
              <li
                key={`${issue.error_code}-${issue.excel_row ?? "x"}-${idx}`}
                className="review-read-error-item"
              >
                <strong>{issue.error_code}</strong>
                <p className="meta" style={{ margin: "0.25rem 0" }}>
                  {issue.user_message || "Revise esta fila antes de finalizar."}
                  {issue.credito ? ` · Crédito ${issue.credito}` : ""}
                  {issue.id_pago ? ` · Pago ${issue.id_pago}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {review ? (
        <>
          <p className="meta">
            {review.summary.pagos ?? review.pagos.length} pagos ·{" "}
            {review.summary.abonos ?? review.abonos.length} abonos ·{" "}
            {review.summary.errors ?? review.errors.length} errores
            {review.etag ? ` · etag listo` : ""}
            {canEdit ? " · edición activa" : " · solo lectura"}
          </p>
          {review.review_excel?.web_url ? (
            <p className="meta">
              <a
                className="text-link"
                href={review.review_excel.web_url}
                target="_blank"
                rel="noreferrer"
              >
                Abrir Excel de revisión en SharePoint
              </a>
            </p>
          ) : null}

          {review.errors.length > 0 ? (
            <div className="review-read-errors" role="region" aria-label="Errores de revisión">
              <h3 className="phase-docs-title">Errores</h3>
              <ul className="review-read-error-list">
                {review.errors.map((err: UiReviewErrorItem) => (
                  <li key={err.row_key} className="review-read-error-item">
                    <strong>
                      {err.credito ? `Crédito ${err.credito}` : "Sin crédito"}
                      {err.tipo_caso ? ` · ${err.tipo_caso}` : ""}
                    </strong>
                    <p className="meta" style={{ margin: "0.25rem 0" }}>
                      {err.descripcion || err.que_debe_hacer || "Caso en hoja Errores"}
                    </p>
                    <div className="review-read-error-actions">
                      {err.credito ? (
                        <button
                          type="button"
                          className="btn secondary"
                          onClick={() => goToCredit(err.credito)}
                        >
                          Ir al crédito
                        </button>
                      ) : null}
                      <RowLinks links={err.links} />
                      {err.requires_regeneration ? (
                        <span className="meta">Puede requerir regenerar el lote</span>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="review-read-tabs" role="tablist" aria-label="Hojas de distribución">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "pagos"}
              className={tab === "pagos" ? "btn secondary is-selected" : "btn secondary"}
              onClick={() => setTab("pagos")}
            >
              Pagos ({review.pagos.length})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "abonos"}
              className={tab === "abonos" ? "btn secondary is-selected" : "btn secondary"}
              onClick={() => setTab("abonos")}
            >
              Abonos ({review.abonos.length})
            </button>
          </div>

          {tab === "pagos" ? (
            <div className="review-read-table-wrap">
              <table className="review-read-table">
                <thead>
                  <tr>
                    <th>Crédito</th>
                    <th>Cliente</th>
                    <th>Monto banco</th>
                    <th>Validar</th>
                    <th>Estado</th>
                    {canEdit ? (
                      <>
                        <th>Aplicar extracto</th>
                        <th>Mora</th>
                        <th>Capital</th>
                        <th>Otros</th>
                        <th>Observación</th>
                      </>
                    ) : (
                      <th>Saldo</th>
                    )}
                    <th>Enlaces</th>
                  </tr>
                </thead>
                <tbody>
                  {review.pagos.length === 0 ? (
                    <tr>
                      <td colSpan={canEdit ? 11 : 7} className="muted">
                        Sin filas de pagos.
                      </td>
                    </tr>
                  ) : (
                    review.pagos.map((row: UiReviewPagoRow) => (
                      <tr
                        key={row.row_key}
                        ref={(el) => {
                          rowRefs.current[row.row_key] = el;
                        }}
                        className={
                          highlightKey === row.row_key ? "review-read-row-highlight" : undefined
                        }
                        data-row-key={row.row_key}
                      >
                        <td>{row.credito || "—"}</td>
                        <td>{row.cliente || "—"}</td>
                        <td>{formatMoney(row.monto_banco)}</td>
                        <td>
                          {canEdit ? (
                            <select
                              aria-label={`Validar pago ${row.credito}`}
                              value={fieldValue(
                                drafts,
                                row.row_key,
                                "validar_pago",
                                row.validar_pago,
                              )}
                              onChange={(e) =>
                                setDraftField(row.row_key, "validar_pago", e.target.value)
                              }
                            >
                              <option value="">—</option>
                              <option value="SI">SI</option>
                              <option value="NO">NO</option>
                            </select>
                          ) : (
                            row.validar_pago || "—"
                          )}
                        </td>
                        <td>
                          {canEdit ? (
                            <input
                              aria-label={`Estado pago ${row.credito}`}
                              value={fieldValue(
                                drafts,
                                row.row_key,
                                "estado_pago",
                                row.estado_pago,
                              )}
                              onChange={(e) =>
                                setDraftField(row.row_key, "estado_pago", e.target.value)
                              }
                            />
                          ) : (
                            row.estado_pago || "—"
                          )}
                        </td>
                        {canEdit ? (
                          <>
                            <td>
                              <input
                                inputMode="decimal"
                                aria-label={`Aplicar extracto ${row.credito}`}
                                value={fieldValue(
                                  drafts,
                                  row.row_key,
                                  "aplicar_a_extracto",
                                  moneyInputValue(row.aplicar_a_extracto),
                                )}
                                onChange={(e) =>
                                  setDraftField(
                                    row.row_key,
                                    "aplicar_a_extracto",
                                    e.target.value,
                                  )
                                }
                              />
                            </td>
                            <td>
                              <input
                                inputMode="decimal"
                                aria-label={`Mora ${row.credito}`}
                                value={fieldValue(
                                  drafts,
                                  row.row_key,
                                  "mora_a_aplicar",
                                  moneyInputValue(row.mora_a_aplicar),
                                )}
                                onChange={(e) =>
                                  setDraftField(row.row_key, "mora_a_aplicar", e.target.value)
                                }
                              />
                            </td>
                            <td>
                              <input
                                inputMode="decimal"
                                aria-label={`Capital ${row.credito}`}
                                value={fieldValue(
                                  drafts,
                                  row.row_key,
                                  "abono_a_capital",
                                  moneyInputValue(row.abono_a_capital),
                                )}
                                onChange={(e) =>
                                  setDraftField(row.row_key, "abono_a_capital", e.target.value)
                                }
                              />
                            </td>
                            <td>
                              <input
                                inputMode="decimal"
                                aria-label={`Otros ${row.credito}`}
                                value={fieldValue(
                                  drafts,
                                  row.row_key,
                                  "otros_valores",
                                  moneyInputValue(row.otros_valores),
                                )}
                                onChange={(e) =>
                                  setDraftField(row.row_key, "otros_valores", e.target.value)
                                }
                              />
                            </td>
                            <td>
                              <input
                                aria-label={`Observación ${row.credito}`}
                                value={fieldValue(
                                  drafts,
                                  row.row_key,
                                  "observacion",
                                  row.observacion,
                                )}
                                onChange={(e) =>
                                  setDraftField(row.row_key, "observacion", e.target.value)
                                }
                              />
                            </td>
                          </>
                        ) : (
                          <td>{formatMoney(row.saldo_por_asignar)}</td>
                        )}
                        <td>
                          <RowLinks links={row.links} />
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="review-read-table-wrap">
              <table className="review-read-table">
                <thead>
                  <tr>
                    <th>Crédito</th>
                    <th>Cliente</th>
                    <th>Monto banco</th>
                    <th>Validar abono</th>
                    <th>Enlaces</th>
                  </tr>
                </thead>
                <tbody>
                  {review.abonos.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="muted">
                        Sin filas de abonos.
                      </td>
                    </tr>
                  ) : (
                    review.abonos.map((row: UiReviewAbonoRow) => (
                      <tr
                        key={row.row_key}
                        ref={(el) => {
                          rowRefs.current[row.row_key] = el;
                        }}
                        className={
                          highlightKey === row.row_key ? "review-read-row-highlight" : undefined
                        }
                        data-row-key={row.row_key}
                      >
                        <td>{row.credito || "—"}</td>
                        <td>{row.cliente || "—"}</td>
                        <td>{formatMoney(row.monto_banco)}</td>
                        <td>
                          {canEdit ? (
                            <select
                              aria-label={`Validar abono ${row.credito}`}
                              value={fieldValue(
                                drafts,
                                row.row_key,
                                "validar_abono",
                                row.validar_abono,
                              )}
                              onChange={(e) =>
                                setDraftField(row.row_key, "validar_abono", e.target.value)
                              }
                            >
                              <option value="">—</option>
                              <option value="SI">SI</option>
                              <option value="NO">NO</option>
                            </select>
                          ) : (
                            row.validar_abono || "—"
                          )}
                        </td>
                        <td>
                          <RowLinks links={row.links} />
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
