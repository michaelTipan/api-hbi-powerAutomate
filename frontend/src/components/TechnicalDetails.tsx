import type { ReactNode } from "react";
import type { UiJobView, UiProcessDetail } from "../types/contract";
import { Disclosure } from "./Disclosure";

function Row({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <p className="meta" style={{ marginTop: "0.5rem" }}>
      <strong style={{ color: "var(--ink)" }}>{label}:</strong> {value}
    </p>
  );
}

/**
 * Datos técnicos (ProcessKey, EstadoProceso, ids de job, claves de
 * idempotencia). Plegado por defecto: no es lenguaje operativo, es evidencia
 * de auditoría/soporte técnico.
 */
export function TechnicalDetails({
  detail,
  job,
}: {
  detail: UiProcessDetail;
  job: UiJobView | null;
}) {
  return (
    <section className="panel">
      <Disclosure summary="Detalles técnicos" defaultOpen={false}>
        <Row label="ProcessKey" value={detail.process_key} />
        <Row label="Estado de control" value={detail.control_estado_proceso} />
        <Row label="Ambiente" value={detail.environment} />
        <Row label="process_id" value={detail.process_id} />
        {job?.job_id && <Row label="Job consultado" value={`${job.type ?? "—"} · ${job.job_id}`} />}
        {detail.active_job?.job_id && (
          <Row
            label="Job activo"
            value={`${detail.active_job.type} · ${detail.active_job.job_id}`}
          />
        )}
        {Object.entries(detail.latest_attempts_by_stage ?? {}).map(([stageKey, attempt]) => (
          <Row
            key={stageKey}
            label={`Último job — ${stageKey}`}
            value={`${attempt.job_type} · ${attempt.job_id}`}
          />
        ))}
        <Row label="Idempotencia Notify" value={detail.idempotency.notify_idempotency_key} />
        <Row label="Idempotencia Merge" value={detail.idempotency.merge_idempotency_key} />
        <Row label="Idempotencia Apply" value={detail.idempotency.apply_idempotency_key} />
        <Row label="Archivo de control" value={detail.files.control_file_path} />
        <Row label="Bitácora de ejecución" value={detail.files.execution_log_path} />
        <Row label="Origen" value={detail.trigger_source} />
        <Row label="Solicitado por" value={detail.requested_by} />
      </Disclosure>
    </section>
  );
}
