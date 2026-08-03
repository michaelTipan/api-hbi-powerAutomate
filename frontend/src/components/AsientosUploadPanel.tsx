import { useState } from "react";
import { postProcessAsiento } from "../api/client";
import { operatorErrorMessage } from "../domain/jobMessages";
import type { UiMergeReadiness } from "../types/contract";

type MissingItem = {
  id_pago: string;
  credito: string;
  tipo_aplicacion?: string;
  label?: string;
};

function normalizeMissing(
  items: Array<Record<string, unknown>>,
): MissingItem[] {
  const out: MissingItem[] = [];
  const seen = new Set<string>();
  for (const raw of items) {
    const id_pago = String(raw.id_pago ?? "").trim();
    const credito = String(
      raw.credito ?? raw.credit ?? raw.credito_digits ?? "",
    ).trim();
    if (!id_pago || !credito) continue;
    const tipo = String(raw.tipo_aplicacion ?? "").trim() || undefined;
    const key = `${id_pago}|${credito}|${tipo || ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      id_pago,
      credito,
      tipo_aplicacion: tipo,
      label: String(raw.user_message || raw.error_code || "").trim() || undefined,
    });
  }
  return out;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("No se pudo leer el archivo."));
    reader.onload = () => {
      const result = String(reader.result || "");
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

/**
 * Panel R3: carga PDF de asientos por id_pago + crédito (sin path SharePoint).
 */
export function AsientosUploadPanel({
  processKey,
  enabled,
  readiness,
  onUploaded,
}: {
  processKey: string;
  enabled: boolean;
  readiness: UiMergeReadiness | null | undefined;
  onUploaded?: () => void;
}) {
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  if (!enabled) return null;

  const missing = normalizeMissing(readiness?.missing_items ?? []);
  const showList = missing.length > 0;

  async function uploadFor(item: MissingItem, file: File | null) {
    if (!file) return;
    const key = `${item.id_pago}|${item.credito}`;
    setBusyKey(key);
    setError(null);
    setInfo(null);
    try {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        throw new Error("Solo se admiten archivos PDF.");
      }
      const content_base64 = await fileToBase64(file);
      const res = await postProcessAsiento(processKey, {
        id_pago: item.id_pago,
        credito: item.credito,
        tipo_aplicacion: item.tipo_aplicacion,
        content_base64,
        source_filename: file.name,
      });
      setInfo(`Cargado: ${res.filename}`);
      onUploaded?.();
    } catch (e) {
      setError(operatorErrorMessage(e, "No pudimos cargar el asiento.").message);
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <section className="panel" id="asientos-upload-panel" aria-labelledby="asientos-upload-title">
      <h2 id="asientos-upload-title" className="section-title">
        Cargar asientos
      </h2>
      <p className="meta" style={{ marginTop: 0 }}>
        Suba el PDF por pago y crédito. La carpeta y el nombre final los define el servidor.
      </p>
      {error ? <div className="error-box">{error}</div> : null}
      {info ? <div className="review-read-info">{info}</div> : null}

      {!showList ? (
        <p className="meta">
          {readiness?.status === "ready"
            ? "Todos los soportes requeridos ya están presentes."
            : "No hay ítems pendientes listados; actualice el detalle tras Notify/Finalize."}
        </p>
      ) : (
        <ul className="asientos-upload-list">
          {missing.map((item) => {
            const key = `${item.id_pago}|${item.credito}|${item.tipo_aplicacion || ""}`;
            const busy = busyKey === `${item.id_pago}|${item.credito}`;
            return (
              <li key={key} className="asientos-upload-item">
                <div>
                  <strong>
                    Pago {item.id_pago} · Crédito {item.credito}
                    {item.tipo_aplicacion ? ` · ${item.tipo_aplicacion}` : ""}
                  </strong>
                  {item.label ? (
                    <p className="meta" style={{ margin: "0.2rem 0 0" }}>
                      {item.label}
                    </p>
                  ) : null}
                </div>
                <label className="btn secondary asientos-upload-btn">
                  {busy ? "Subiendo…" : "Elegir PDF"}
                  <input
                    type="file"
                    accept="application/pdf,.pdf"
                    disabled={busy || busyKey != null}
                    hidden
                    onChange={(e) => {
                      const f = e.target.files?.[0] ?? null;
                      e.target.value = "";
                      void uploadFor(item, f);
                    }}
                  />
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
