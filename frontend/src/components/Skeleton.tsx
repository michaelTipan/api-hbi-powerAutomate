/** Placeholders de carga inicial: reemplazan un "Cargando…" desnudo. */

export function CardSkeleton() {
  return (
    <div className="skeleton-card rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="h-4 w-1/3 rounded bg-zinc-200 animate-pulse skeleton-line-title" />
      <div className="mt-3 h-3 w-full rounded bg-zinc-100 animate-pulse skeleton-line" />
      <div className="mt-2 h-3 w-2/3 rounded bg-zinc-100 animate-pulse skeleton-line skeleton-line-short" />
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
    <section className="panel rounded-xl border border-zinc-200 bg-white p-6 shadow-sm" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className={`h-3 rounded bg-zinc-100 animate-pulse skeleton-line${i === 0 ? " h-5 w-1/3 skeleton-line-title" : " w-full"}`}
          />
        ))}
      </div>
    </section>
  );
}
