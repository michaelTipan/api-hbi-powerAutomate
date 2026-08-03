import { useEffect, useRef, useState } from "react";
import { fetchProcessReview } from "../api/client";
import { operatorErrorMessage } from "../domain/jobMessages";
import type {
  UiLink,
  UiReviewAbonoRow,
  UiReviewErrorItem,
  UiReviewPagoRow,
  UiReviewResponse,
} from "../types/contract";

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("es-CO", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
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

/**
 * Panel R0: muestra el Excel de revisión en solo lectura dentro del detalle.
 * Sin edición / Guardar / PATCH.
 */
export function ReviewReadPanel({
  processKey,
  enabled,
  onNavigateToCredit,
}: {
  processKey: string;
  enabled: boolean;
  onNavigateToCredit?: (credito: string) => void;
}) {
  const [review, setReview] = useState<UiReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"pagos" | "abonos">("pagos");
  const [highlightKey, setHighlightKey] = useState<string | null>(null);
  const rowRefs = useRef<Record<string, HTMLTableRowElement | null>>({});

  useEffect(() => {
    if (!enabled || !processKey) {
      setReview(null);
      setError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchProcessReview(processKey);
        if (!cancelled) setReview(data);
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

  if (!enabled) return null;

  return (
    <section className="panel" id="review-read-panel" aria-labelledby="review-read-title">
      <h2 id="review-read-title" className="section-title">
        Revisión del lote
      </h2>
      <p className="meta" style={{ marginTop: 0 }}>
        Solo lectura. Los cambios en Excel Online seguirán funcionando; la edición en UI llega en
        una fase posterior.
      </p>

      {loading ? <p className="meta">Cargando revisión…</p> : null}
      {error ? <div className="error-box">{error}</div> : null}

      {review ? (
        <>
          <p className="meta">
            {review.summary.pagos ?? review.pagos.length} pagos ·{" "}
            {review.summary.abonos ?? review.abonos.length} abonos ·{" "}
            {review.summary.errors ?? review.errors.length} errores
            {review.etag ? ` · etag listo` : ""}
            {review.read_only ? " · solo lectura" : ""}
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
                    <th>Saldo</th>
                    <th>Enlaces</th>
                  </tr>
                </thead>
                <tbody>
                  {review.pagos.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="muted">
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
                        <td>{row.validar_pago || "—"}</td>
                        <td>{row.estado_pago || "—"}</td>
                        <td>{formatMoney(row.saldo_por_asignar)}</td>
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
