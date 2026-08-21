import { useId, type ReactNode } from "react";
import { Modal } from "./Modal";
import { LoadingButton } from "./LoadingButton";

/** Modal de confirmación estándar: título + contenido + acción primaria/cancelar. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  busyLabel,
  busy = false,
  confirmDisabled = false,
  confirmDisabledTitle,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  busy?: boolean;
  /** Bloquea confirmar (p. ej. preview aún cargando o fallida). */
  confirmDisabled?: boolean;
  confirmDisabledTitle?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  return (
    <Modal titleId={titleId} title={title} descriptionId={descriptionId} onClose={onCancel} closeDisabled={busy}>
      <div id={descriptionId} className="confirm-dialog-body">
        {children}
      </div>
      <div className="actions">
        <LoadingButton
          busy={busy}
          busyLabel={busyLabel}
          disabled={confirmDisabled}
          title={confirmDisabled ? confirmDisabledTitle : undefined}
          onClick={onConfirm}
        >
          {confirmLabel}
        </LoadingButton>
        <button type="button" className="btn secondary" disabled={busy} onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </Modal>
  );
}
