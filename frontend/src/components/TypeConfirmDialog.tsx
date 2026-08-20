import { useId, useState, type ReactNode } from "react";
import { Modal } from "./Modal";
import { LoadingButton } from "./LoadingButton";

/** Confirmación fuerte: el operador debe escribir exactamente la palabra dada. */
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
      <div id={descriptionId} className="confirm-dialog-body">
        {children}
      </div>
      <label className="type-confirm-field" htmlFor={confirmInputId}>
        <span className="type-confirm-label">
          Para confirmar, escriba <strong>{confirmWord}</strong>
        </span>
        <input
          id={confirmInputId}
          className="type-confirm-input"
          type="text"
          autoComplete="off"
          spellCheck={false}
          value={typed}
          disabled={busy}
          placeholder={confirmWord}
          onChange={(e) => setTyped(e.target.value)}
        />
      </label>
      <div className="actions">
        <LoadingButton
          busy={busy}
          busyLabel={busyLabel}
          disabled={!canConfirm}
          onClick={() => onConfirm()}
        >
          {confirmLabel}
        </LoadingButton>
        <button type="button" className="btn secondary" disabled={busy} onClick={onCancel}>
          Volver
        </button>
      </div>
    </Modal>
  );
}
