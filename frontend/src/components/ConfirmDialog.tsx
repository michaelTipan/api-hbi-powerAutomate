import { useId, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "./Modal";
import { LoadingButton } from "./LoadingButton";

/**
 * Modal de confirmación estándar.
 * Footer (Carbon/Material): Cancelar secondary a la izquierda, Primary a la derecha.
 */
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
      <div id={descriptionId} className="confirm-dialog-body space-y-3 text-sm text-zinc-700">
        {children}
      </div>
      <div className="modal-actions flex flex-wrap justify-end gap-2 pt-4">
        <Button type="button" variant="secondary" disabled={busy} onClick={onCancel}>
          Cancelar
        </Button>
        <LoadingButton
          busy={busy}
          busyLabel={busyLabel}
          disabled={confirmDisabled}
          title={confirmDisabled ? confirmDisabledTitle : undefined}
          className="primary"
          onClick={onConfirm}
        >
          {confirmLabel}
        </LoadingButton>
      </div>
    </Modal>
  );
}
