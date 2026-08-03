import { useId } from "react";
import type { UiLink } from "../types/contract";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";
import { operatorDocumentLabel } from "../domain/processPhases";

export type JobStatusModalView =
  | {
      kind: "processing";
      title: string;
      message?: string | null;
      /** Tras aceptar el POST: se puede cerrar sin cancelar el job. */
      dismissible?: boolean;
      dismissLabel?: string;
    }
  | {
      kind: "success";
      title: string;
      message: string;
      /** Enlaces 1:1 post-sync (p. ej. un PDF consolidado o el PDF del correo). */
      links?: readonly UiLink[];
      /**
       * CTA agrupado cuando hay N≥2 del mismo catálogo (abre LinkCatalogDrawer).
       * Mutuamente excluyente con `links` en la práctica.
       */
      catalogCta?: {
        label: string;
        onOpen: () => void;
      };
      dismissLabel?: string;
    }
  | {
      kind: "warning";
      title: string;
      message: string;
      dismissLabel?: string;
    }
  | {
      kind: "error";
      title: string;
      message: string;
      dismissLabel?: string;
    };

/**
 * Modal de progreso / resultado.
 * - Aceptando POST: no cerrable.
 * - Job en curso (dismissible): se puede cerrar; el trabajo sigue en segundo plano.
 * - Resultado: CTA Continuar / Entendido (+ links opcionales).
 */
export function JobStatusModal({
  view,
  onDismiss,
}: {
  view: JobStatusModalView;
  onDismiss: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const processingLocked = view.kind === "processing" && !view.dismissible;
  const showDismiss =
    view.kind !== "processing" || Boolean(view.dismissible);
  const successLinks =
    view.kind === "success" && !view.catalogCta
      ? (view.links ?? []).filter((l) => Boolean(l.web_url))
      : [];
  const catalogCta = view.kind === "success" ? view.catalogCta : undefined;

  const resultToneClass =
    view.kind === "success"
      ? "is-success"
      : view.kind === "warning"
        ? "is-warning"
        : view.kind === "error"
          ? "is-error"
          : "";

  const defaultDismissLabel =
    view.kind === "processing"
      ? "Seguir en segundo plano"
      : view.kind === "success"
        ? "Continuar"
        : view.kind === "warning"
          ? "Actualizar estado"
          : "Entendido";

  return (
    <Modal
      titleId={titleId}
      title={view.title}
      descriptionId={descriptionId}
      onClose={onDismiss}
      closeDisabled={processingLocked}
    >
      <div id={descriptionId} className="job-status-modal-body">
        {view.kind === "processing" ? (
          <div className="job-status-modal-processing" role="status" aria-live="polite" aria-busy="true">
            <Spinner size="md" label={view.title} />
            <p className="meta" style={{ margin: 0 }}>
              {view.message || "El sistema está trabajando. Espere un momento…"}
            </p>
          </div>
        ) : (
          <div
            className={`job-status-modal-result ${resultToneClass}`}
            role="status"
          >
            <p style={{ margin: 0 }}>{view.message}</p>
            {catalogCta ? (
              <ul className="job-status-modal-links">
                <li>
                  <button
                    type="button"
                    className="job-status-modal-catalog-cta"
                    onClick={catalogCta.onOpen}
                  >
                    {catalogCta.label}
                  </button>
                </li>
              </ul>
            ) : null}
            {successLinks.length > 0 ? (
              <ul className="job-status-modal-links">
                {successLinks.map((link) => (
                  <li key={link.rel}>
                    <a href={link.web_url!} target="_blank" rel="noreferrer">
                      {operatorDocumentLabel(link)}
                    </a>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )}
      </div>
      {showDismiss ? (
        <div className="actions" style={{ marginTop: "1rem" }}>
          <button type="button" className="btn" onClick={onDismiss}>
            {view.dismissLabel || defaultDismissLabel}
          </button>
        </div>
      ) : null}
    </Modal>
  );
}
