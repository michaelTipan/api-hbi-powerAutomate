import { useId } from "react";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

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
 * - Resultado: CTA Continuar / Entendido.
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
            className={
              view.kind === "success"
                ? "job-status-modal-result is-success"
                : view.kind === "warning"
                  ? "job-status-modal-result is-warning"
                  : "job-status-modal-result is-error"
            }
            role="status"
          >
            <p style={{ margin: 0 }}>{view.message}</p>
          </div>
        )}
      </div>
      {showDismiss ? (
        <div className="actions" style={{ marginTop: "1rem" }}>
          <button type="button" className="btn" onClick={onDismiss}>
            {view.kind === "processing"
              ? view.dismissLabel || "Seguir en segundo plano"
              : view.dismissLabel ||
                (view.kind === "success"
                  ? "Continuar"
                  : view.kind === "warning"
                    ? "Actualizar estado"
                    : "Entendido")}
          </button>
        </div>
      ) : null}
    </Modal>
  );
}
