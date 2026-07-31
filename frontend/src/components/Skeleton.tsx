/** Placeholders de carga inicial: reemplazan un "Cargando…" desnudo. */

export function CardSkeleton() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-line skeleton-line-title" />
      <div className="skeleton-line" />
      <div className="skeleton-line skeleton-line-short" />
    </div>
  );
}

export function PageSkeleton({
  rows = 3,
  label = "Cargando información…",
}: {
  rows?: number;
  label?: string;
}) {
  return (
    <section className="panel" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div aria-hidden="true">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className={`skeleton-line${i === 0 ? " skeleton-line-title" : ""}`}
          />
        ))}
      </div>
    </section>
  );
}
