/** Aviso persistente cuando el sondeo de un job viene fallando repetidas veces. */
export function PollingStatus({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <p className="meta polling-status" role="status" aria-live="polite">
      {message}
    </p>
  );
}
