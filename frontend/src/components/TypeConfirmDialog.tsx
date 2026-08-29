import { useId, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "./Modal";
import { LoadingButton } from "./LoadingButton";

/**
 * Confirmación fuerte (destructiva): escribir la palabra exacta.
 * Footer: Volver secondary a la izquierda; confirm danger a la derecha.
 */
export function TypeConfirmDialog({
  title,
  children,
  confirmWord = "CANCELAR",
  confirmLabel,
  busyLabel,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmWord?: string;
  confirmLabel: string;
  busyLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const confirmInputId = useId();
  const [typed, setTyped] = useState("");

  const canConfirm = typed.trim() === confirmWord && !busy;

  return (
    <Modal
      titleId={titleId}
      title={title}
      descriptionId={descriptionId}
      onClose={onCancel}
      closeDisabled={busy}
    >
      <div id={descriptionId} className="confirm-dialog-body space-y-3 text-sm text-zinc-700">
        {children}
      </div>
      <label className="type-confirm-field mt-4 block space-y-2" htmlFor={confirmInputId}>
        <span className="type-confirm-label text-sm text-zinc-700">
          Para confirmar, escriba <strong>{confirmWord}</strong>
        </span>
        <input
          id={confirmInputId}
          className="type-confirm-input w-full rounded-md border border-zinc-200 px-3 py-2 text-sm"
          type="text"
          autoComplete="off"
          spellCheck={false}
          value={typed}
          disabled={busy}
          placeholder={confirmWord}
          onChange={(e) => setTyped(e.target.value)}
        />
      </label>
      <div className="modal-actions flex flex-wrap justify-end gap-2 pt-4">
        <Button type="button" variant="secondary" disabled={busy} onClick={onCancel}>
          Volver
        </Button>
        <LoadingButton
          variant="danger"
          busy={busy}
          busyLabel={busyLabel}
          disabled={!canConfirm}
          onClick={() => onConfirm()}
        >
          {confirmLabel}
        </LoadingButton>
      </div>
    </Modal>
  );
}
