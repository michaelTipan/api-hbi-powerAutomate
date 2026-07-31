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
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  return (
    <Modal titleId={titleId} title={title} descriptionId={descriptionId} onClose={onCancel} closeDisabled={busy}>
      <div id={descriptionId}>{children}</div>
      <div className="actions">
        <LoadingButton busy={busy} busyLabel={busyLabel} onClick={onConfirm}>
          {confirmLabel}
        </LoadingButton>
        <button type="button" className="btn secondary" disabled={busy} onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </Modal>
  );
}
