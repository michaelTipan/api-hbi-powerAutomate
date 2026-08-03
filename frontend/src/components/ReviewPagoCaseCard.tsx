import {
  appliedBreakdown,
  formatMoneyCo,
  pagoNeedsAttention,
} from "../domain/reviewApplication";
import type { UiLink, UiReviewPagoRow } from "../types/contract";

type DraftFields = Record<string, string>;
type DraftMap = Record<string, DraftFields>;

function RowLinks({ links }: { links: readonly UiLink[] }) {
  if (!links.length) return null;
  return (
    <div className="review-case-links">
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
    </div>
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

function moneyInputValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return String(value);
}

/**
 * Tarjeta de un caso de pago: a quién, monto banco y qué se aplicará.
 */
export function ReviewPagoCaseCard({
  row,
  drafts,
  canEdit,
  expanded,
  highlighted,
  onToggle,
  onDraft,
  cardRef,
}: {
  row: UiReviewPagoRow;
  drafts: DraftMap;
  canEdit: boolean;
  expanded: boolean;
  highlighted: boolean;
  onToggle: () => void;
  onDraft: (field: string, value: string) => void;
  cardRef?: (el: HTMLElement | null) => void;
}) {
  const draft = drafts[row.row_key];
  const br = appliedBreakdown(row, draft);
  const attention = pagoNeedsAttention(row, draft);
  const validar = fieldValue(drafts, row.row_key, "validar_pago", row.validar_pago);

  return (
    <article
      ref={cardRef}
      className={[
        "review-case-card",
        attention ? "review-case-card--attention" : "",
        highlighted ? "review-case-card--highlight" : "",
        expanded ? "review-case-card--open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-row-key={row.row_key}
    >
      <button
        type="button"
        className="review-case-card__header"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <div className="review-case-card__who">
          <strong className="review-case-card__cliente">
            {row.cliente || "Sin cliente"}
          </strong>
          <span className="meta">
            Crédito {row.credito || "—"}
            {row.id_pago ? ` · Pago ${row.id_pago}` : ""}
          </span>
        </div>
        <div className="review-case-card__amounts">
          <div>
            <span className="review-case-card__label">Monto banco</span>
            <strong>{formatMoneyCo(br.banco)}</strong>
          </div>
          <div>
            <span className="review-case-card__label">Se aplicará</span>
            <strong>{formatMoneyCo(br.total)}</strong>
          </div>
          <div>
            <span className="review-case-card__label">Saldo</span>
            <strong
              className={
                br.saldo !== null && Math.abs(br.saldo) > 0.009
                  ? "review-case-card__saldo-bad"
                  : undefined
              }
            >
              {formatMoneyCo(br.saldo)}
            </strong>
          </div>
        </div>
        <span className="review-case-card__badge">
          {attention ? "Revisar" : validar === "SI" ? "Validar SI" : validar || "—"}
        </span>
      </button>

      {expanded ? (
        <div className="review-case-card__body">
          <p className="review-case-card__summary">
            Aplicará <strong>{formatMoneyCo(br.total)}</strong> a{" "}
            <strong>{row.cliente || "cliente"}</strong> (crédito{" "}
            <strong>{row.credito || "—"}</strong>
            {row.id_pago ? (
              <>
                , pago <strong>{row.id_pago}</strong>
              </>
            ) : null}
            ).
          </p>

          <dl className="review-case-card__breakdown">
            <div>
              <dt>Extracto</dt>
              <dd>{formatMoneyCo(br.extracto)}</dd>
            </div>
            <div>
              <dt>Mora</dt>
              <dd>{formatMoneyCo(br.mora)}</dd>
            </div>
            <div>
              <dt>Capital</dt>
              <dd>{formatMoneyCo(br.capital)}</dd>
            </div>
            <div>
              <dt>Otros</dt>
              <dd>{formatMoneyCo(br.otros)}</dd>
            </div>
          </dl>

          {canEdit ? (
            <div className="review-case-card__form">
              <label>
                Validar pago
                <select
                  aria-label={`Validar pago ${row.credito}`}
                  value={validar}
                  onChange={(e) => onDraft("validar_pago", e.target.value)}
                >
                  <option value="">—</option>
                  <option value="SI">SI</option>
                  <option value="NO">NO</option>
                </select>
              </label>
              <label>
                Estado pago
                <input
                  aria-label={`Estado pago ${row.credito}`}
                  value={fieldValue(
                    drafts,
                    row.row_key,
                    "estado_pago",
                    row.estado_pago,
                  )}
                  onChange={(e) => onDraft("estado_pago", e.target.value)}
                />
              </label>
              <label>
                Aplicar a extracto
                <input
                  inputMode="decimal"
                  aria-label={`Aplicar extracto ${row.credito}`}
                  value={fieldValue(
                    drafts,
                    row.row_key,
                    "aplicar_a_extracto",
                    moneyInputValue(row.aplicar_a_extracto),
                  )}
                  onChange={(e) => onDraft("aplicar_a_extracto", e.target.value)}
                />
              </label>
              <label>
                Mora a aplicar
                <input
                  inputMode="decimal"
                  aria-label={`Mora ${row.credito}`}
                  value={fieldValue(
                    drafts,
                    row.row_key,
                    "mora_a_aplicar",
                    moneyInputValue(row.mora_a_aplicar),
                  )}
                  onChange={(e) => onDraft("mora_a_aplicar", e.target.value)}
                />
              </label>
              <label>
                Abono a capital
                <input
                  inputMode="decimal"
                  aria-label={`Capital ${row.credito}`}
                  value={fieldValue(
                    drafts,
                    row.row_key,
                    "abono_a_capital",
                    moneyInputValue(row.abono_a_capital),
                  )}
                  onChange={(e) => onDraft("abono_a_capital", e.target.value)}
                />
              </label>
              <label>
                Otros valores
                <input
                  inputMode="decimal"
                  aria-label={`Otros ${row.credito}`}
                  value={fieldValue(
                    drafts,
                    row.row_key,
                    "otros_valores",
                    moneyInputValue(row.otros_valores),
                  )}
                  onChange={(e) => onDraft("otros_valores", e.target.value)}
                />
              </label>
              <label className="review-case-card__full">
                Observación
                <input
                  aria-label={`Observación ${row.credito}`}
                  value={fieldValue(
                    drafts,
                    row.row_key,
                    "observacion",
                    row.observacion,
                  )}
                  onChange={(e) => onDraft("observacion", e.target.value)}
                />
              </label>
            </div>
          ) : (
            <p className="meta">
              Validar: {row.validar_pago || "—"} · Estado: {row.estado_pago || "—"}
              {row.observacion ? ` · ${row.observacion}` : ""}
            </p>
          )}

          <RowLinks links={row.links} />
        </div>
      ) : null}
    </article>
  );
}
