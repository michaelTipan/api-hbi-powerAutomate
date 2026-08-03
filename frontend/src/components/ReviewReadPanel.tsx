import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchProcessReview,
  patchProcessReview,
  postProcessReviewPreflight,
} from "../api/client";
import { UiApiError } from "../api/errors";
import { operatorErrorMessage } from "../domain/jobMessages";
import {
  filterPagoRows,
  formatMoneyCo,
  pagoNeedsAttention,
} from "../domain/reviewApplication";
import type {
  UiLink,
  UiReviewAbonoRow,
  UiReviewErrorItem,
  UiReviewPreflightIssue,
  UiReviewResponse,
  UiReviewRowPatch,
} from "../types/contract";
import { ReviewPagoCaseCard } from "./ReviewPagoCaseCard";

export type ReviewPanelSync = {
  etag: string | null;
  dirty: boolean;
  getChanges: () => UiReviewRowPatch[];
  clearDrafts: () => void;
  reload: () => Promise<void>;
};

type DraftFields = Record<string, string>;
type DraftMap = Record<string, DraftFields>;

const PAGE_SIZE = 8;

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

function isFileLockedError(e: unknown): boolean {
  if (e instanceof UiApiError) {
    if (e.errorCode === "sharepoint_file_locked" || e.errorCode === "file_locked") {
      return true;
    }
    const blob = `${e.userMessage} ${e.message}`.toLowerCase();
    return blob.includes("423") || blob.includes("locked") || blob.includes("bloqueado");
  }
  if (e instanceof Error) {
    const m = e.message.toLowerCase();
    return m.includes("423") || m.includes("locked") || m.includes("bloqueado");
  }
  return false;
}

/**
 * Panel de revisión: tarjetas por caso (escala a 15+) + edición R1.
 */
export function ReviewReadPanel({
  processKey,
  enabled,
  editEnabled = false,
  onNavigateToCredit,
  onSync,
  onRequestRegenerate,
}: {
  processKey: string;
  enabled: boolean;
  editEnabled?: boolean;
  onNavigateToCredit?: (credito: string) => void;
  onSync?: (sync: ReviewPanelSync) => void;
  onRequestRegenerate?: () => void;
}) {
  const [review, setReview] = useState<UiReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorNext, setErrorNext] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightIssues, setPreflightIssues] = useState<UiReviewPreflightIssue[]>(
    [],
  );
  const [tab, setTab] = useState<"pagos" | "abonos">("pagos");
  const [highlightKey, setHighlightKey] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [page, setPage] = useState(0);
  const [drafts, setDrafts] = useState<DraftMap>({});
  const rowRefs = useRef<Record<string, HTMLElement | null>>({});

  const dirty = Object.keys(drafts).length > 0;
  const canEdit = Boolean(editEnabled && review && !review.read_only);

  const filteredPagos = useMemo(() => {
    if (!review) return [];
    let rows = filterPagoRows(review.pagos, query);
    if (onlyAttention) {
      rows = rows.filter((r) => pagoNeedsAttention(r, drafts[r.row_key]));
    }
    return rows;
  }, [review, query, onlyAttention, drafts]);

  const pageCount = Math.max(1, Math.ceil(filteredPagos.length / PAGE_SIZE));
  const pageSafe = Math.min(page, pageCount - 1);
  const pageRows = filteredPagos.slice(
    pageSafe * PAGE_SIZE,
    pageSafe * PAGE_SIZE + PAGE_SIZE,
  );

  const attentionCount = useMemo(() => {
    if (!review) return 0;
    return review.pagos.filter((r) => pagoNeedsAttention(r, drafts[r.row_key]))
      .length;
  }, [review, drafts]);

  async function reloadReview() {
    const data = await fetchProcessReview(processKey);
    setReview(data);
    setDrafts({});
    return data;
  }

  useEffect(() => {
    if (!onSync) return;
    onSync({
      etag: review?.etag ?? null,
      dirty,
      getChanges: () => buildChanges(drafts),
      clearDrafts: () => setDrafts({}),
      reload: async () => {
        await reloadReview();
      },
    });
  }, [onSync, review?.etag, dirty, drafts, processKey]);

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
      setErrorNext(null);
      setInfo(null);
      setPreflightIssues([]);
      try {
        const data = await fetchProcessReview(processKey);
        if (!cancelled) {
          setReview(data);
          setDrafts({});
          const first = data.pagos[0]?.row_key ?? null;
          setOpenKey(first);
        }
      } catch (e) {
        if (!cancelled) {
          setReview(null);
          const op = operatorErrorMessage(e, "No pudimos cargar la revisión.");
          setError(
            isFileLockedError(e)
              ? "El Excel de revisión está bloqueado en SharePoint (suele estar abierto en Excel). Cierre el archivo y reintente."
              : op.message,
          );
          setErrorNext(
            isFileLockedError(e)
              ? "Cierre el libro en Excel Desktop / Online y pulse Actualizar."
              : op.nextAction,
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
      setOpenKey(inPagos.row_key);
      setQuery("");
      setOnlyAttention(false);
      const idx = review.pagos.findIndex((p) => p.row_key === inPagos.row_key);
      if (idx >= 0) setPage(Math.floor(idx / PAGE_SIZE));
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
      return;
    }
  }

  async function onSave() {
    if (!review?.etag || !dirty) return;
    setSaving(true);
    setError(null);
    setErrorNext(null);
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
      if (isFileLockedError(e)) {
        setError(
          "No se pudo guardar: el Excel está abierto o bloqueado en SharePoint.",
        );
        setErrorNext(
          "Cierre el archivo de revisión en Excel y vuelva a Guardar.",
        );
      } else {
        const msg = operatorErrorMessage(e, "No pudimos guardar la revisión.");
        setError(msg.message);
        setErrorNext(msg.nextAction);
      }
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
    setErrorNext(null);
    setInfo(null);
    try {
      const res = await postProcessReviewPreflight(processKey);
      setPreflightIssues(res.issues);
      if (res.ok) {
        setInfo("Preflight OK: el lote cumple las reglas de Finalizar.");
      } else {
        setInfo(
          `Preflight encontró ${res.issue_count} problema(s). Corríjalos aquí o regenere tras la hoja Errores.`,
        );
      }
    } catch (e) {
      if (isFileLockedError(e)) {
        setError(
          "No se pudo validar: el Excel de revisión está bloqueado (abierto).",
        );
        setErrorNext("Cierre el Excel y ejecute de nuevo «Comprobar antes de finalizar».");
      } else {
        const op = operatorErrorMessage(e, "No pudimos ejecutar el preflight.");
        setError(op.message);
        setErrorNext(op.nextAction);
      }
    } finally {
      setPreflightBusy(false);
    }
  }

  if (!enabled) return null;

  const requiresRegen =
    Boolean(review?.requires_regeneration) ||
    (review?.errors.some((e) => e.requires_regeneration) ?? false);

  return (
    <section
      className="panel panel-emphasis"
      id="review-read-panel"
      aria-labelledby="review-read-title"
    >
      <h2 id="review-read-title" className="section-title">
        Validación de casos de pago
      </h2>
      <p className="meta" style={{ marginTop: 0 }}>
        {canEdit
          ? "Revise cada caso: a quién se aplica y qué montos. Con muchos pagos use el buscador o «Solo pendientes». Guarde borradores; Finalizar exige cuadre y reglas de negocio."
          : editEnabled
            ? "Cargando modo edición…"
            : "Solo lectura. Active UI_REVIEW_EDIT_ENABLED en sandbox para editar desde la UI."}
      </p>

      {loading ? <p className="meta">Cargando revisión…</p> : null}
      {error ? (
        <div className="error-box" role="alert">
          <p style={{ margin: 0 }}>{error}</p>
          {errorNext ? <p className="meta">{errorNext}</p> : null}
        </div>
      ) : null}
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
          <button
            type="button"
            className="btn secondary"
            disabled={loading || saving}
            onClick={() => void reloadReview().catch(() => undefined)}
          >
            Actualizar desde SharePoint
          </button>
        </div>
      ) : null}

      {requiresRegen && onRequestRegenerate ? (
        <div className="review-read-regen" role="region">
          <p>
            Hay errores en la hoja <strong>Errores</strong> o el lote requiere
            regeneración. Corrija el Excel de entrada / errores y regenere el
            archivo de revisión.
          </p>
          <button type="button" className="btn primary" onClick={onRequestRegenerate}>
            Regenerar archivo de revisión
          </button>
        </div>
      ) : null}

      {preflightIssues.length > 0 ? (
        <div
          className="review-read-preflight"
          role="region"
          aria-label="Resultado preflight"
        >
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
                {issue.credito ? (
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={() => goToCredit(issue.credito || "")}
                  >
                    Ir al caso
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {review ? (
        <>
          <div className="review-read-summary-bar">
            <span>
              {(review.summary?.pagos ?? review.pagos.length)} pagos ·{" "}
              {(review.summary?.abonos ?? review.abonos.length)} abonos ·{" "}
              {(review.summary?.errors ?? review.errors.length)} errores
            </span>
            {attentionCount > 0 ? (
              <span className="review-read-summary-warn">
                {attentionCount} caso(s) con Validar=SI incompletos o descuadrados
              </span>
            ) : null}
          </div>

          {review.errors.length > 0 ? (
            <div
              className="review-read-errors"
              role="region"
              aria-label="Errores de revisión"
            >
              <h3 className="phase-docs-title">Hoja Errores</h3>
              <p className="meta">
                Corrija estos casos y regenere el lote si se indica. Finalizar no
                avanzará mientras existan errores abiertos.
              </p>
              <ul className="review-read-error-list">
                {review.errors.map((err: UiReviewErrorItem) => (
                  <li key={err.row_key} className="review-read-error-item">
                    <strong>
                      {err.cliente ? `${err.cliente} · ` : ""}
                      {err.credito ? `Crédito ${err.credito}` : "Sin crédito"}
                      {err.tipo_caso ? ` · ${err.tipo_caso}` : ""}
                    </strong>
                    <p className="meta" style={{ margin: "0.25rem 0" }}>
                      {err.descripcion ||
                        err.que_debe_hacer ||
                        "Caso en hoja Errores"}
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
                        <span className="meta">Requiere regenerar el lote</span>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div
            className="review-read-tabs"
            role="tablist"
            aria-label="Hojas de distribución"
          >
            <button
              type="button"
              role="tab"
              aria-selected={tab === "pagos"}
              className={
                tab === "pagos" ? "btn secondary is-selected" : "btn secondary"
              }
              onClick={() => setTab("pagos")}
            >
              Pagos ({review.pagos.length})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "abonos"}
              className={
                tab === "abonos" ? "btn secondary is-selected" : "btn secondary"
              }
              onClick={() => setTab("abonos")}
            >
              Abonos ({review.abonos.length})
            </button>
          </div>

          {tab === "pagos" ? (
            <>
              <div className="review-case-toolbar">
                <label className="review-case-search">
                  Buscar caso
                  <input
                    type="search"
                    placeholder="Cliente, crédito o id pago…"
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setPage(0);
                    }}
                  />
                </label>
                <label className="review-case-filter">
                  <input
                    type="checkbox"
                    checked={onlyAttention}
                    onChange={(e) => {
                      setOnlyAttention(e.target.checked);
                      setPage(0);
                    }}
                  />
                  Solo pendientes / descuadrados
                </label>
              </div>

              {pageRows.length === 0 ? (
                <p className="muted">No hay casos con ese filtro.</p>
              ) : (
                <div className="review-case-list" role="list">
                  {pageRows.map((row) => (
                    <ReviewPagoCaseCard
                      key={row.row_key}
                      row={row}
                      drafts={drafts}
                      canEdit={canEdit}
                      expanded={openKey === row.row_key}
                      highlighted={highlightKey === row.row_key}
                      onToggle={() =>
                        setOpenKey((k) =>
                          k === row.row_key ? null : row.row_key,
                        )
                      }
                      onDraft={(field, value) =>
                        setDraftField(row.row_key, field, value)
                      }
                      cardRef={(el) => {
                        rowRefs.current[row.row_key] = el;
                      }}
                    />
                  ))}
                </div>
              )}

              {pageCount > 1 ? (
                <div className="review-case-pager">
                  <button
                    type="button"
                    className="btn secondary"
                    disabled={pageSafe <= 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                  >
                    Anterior
                  </button>
                  <span className="meta">
                    Página {pageSafe + 1} de {pageCount} · {filteredPagos.length}{" "}
                    caso(s)
                  </span>
                  <button
                    type="button"
                    className="btn secondary"
                    disabled={pageSafe >= pageCount - 1}
                    onClick={() =>
                      setPage((p) => Math.min(pageCount - 1, p + 1))
                    }
                  >
                    Siguiente
                  </button>
                </div>
              ) : null}
            </>
          ) : (
            <div className="review-read-table-wrap">
              <table className="review-read-table">
                <thead>
                  <tr>
                    <th>Cliente</th>
                    <th>Crédito</th>
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
                      <tr key={row.row_key}>
                        <td>{row.cliente || "—"}</td>
                        <td>{row.credito || "—"}</td>
                        <td>{formatMoneyCo(row.monto_banco)}</td>
                        <td>{row.validar_abono || "—"}</td>
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
