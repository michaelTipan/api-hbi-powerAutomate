import { useId } from "react";
import type { UiLink } from "../types/contract";
import type { JobFailureIssue } from "../domain/finalizeJobFailure";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";
import { operatorDocumentLabel } from "../domain/processPhases";

export type JobStatusModalView =
  | {
      kind: "processing";
      title: string;
      message?: string | null;
      /** Tras aceptar el POST: se puede cerrar sin cancelar el job. */
      dismissible?: boolean;
      dismissLabel?: string;
    }
  | {
      kind: "success";
      title: string;
      message: string;
      /** Enlaces 1:1 post-sync (p. ej. un PDF consolidado o el PDF del correo). */
      links?: readonly UiLink[];
      /**
       * CTA agrupado cuando hay N≥2 del mismo catálogo (abre LinkCatalogDrawer).
       * Mutuamente excluyente con `links` en la práctica.
       */
      catalogCta?: {
        label: string;
        onOpen: () => void;
      };
      /** CTA secundario (p. ej. abrir modal de problemas). */
      secondaryCta?: {
        label: string;
        onClick: () => void;
      };
      dismissLabel?: string;
    }
  | {
      kind: "warning";
      title: string;
      message: string;
      links?: readonly UiLink[];
      issues?: readonly JobFailureIssue[];
      /** CTA secundario (p. ej. «Ver problemas de amortización»). */
      secondaryCta?: {
        label: string;
        onClick: () => void;
      };
      dismissLabel?: string;
    }
  | {
      kind: "error";
      title: string;
      message: string;
      links?: readonly UiLink[];
      issues?: readonly JobFailureIssue[];
      secondaryCta?: {
        label: string;
        onClick: () => void;
      };
      dismissLabel?: string;
    };

const resultToneClasses = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-950",
  warning: "border-amber-200 bg-amber-50 text-amber-950",
  error: "border-red-200 bg-red-50 text-red-950",
} as const;

/**
 * Modal de progreso / resultado.
 * - Aceptando POST: no cerrable.
 * - Job en curso (dismissible): se puede cerrar; el trabajo sigue en segundo plano.
 * - Resultado: CTA Continuar / Entendido (+ links e issues opcionales).
 */
export function JobStatusModal({
  view,
  onDismiss,
}: {
  view: JobStatusModalView;
  onDismiss: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const processingLocked = view.kind === "processing" && !view.dismissible;
  const showDismiss =
    view.kind !== "processing" || Boolean(view.dismissible);
  const successLinks =
    view.kind === "success" && !view.catalogCta
      ? (view.links ?? []).filter((l) => Boolean(l.web_url))
      : [];
  const resultLinks =
    view.kind === "error" || view.kind === "warning"
      ? (view.links ?? []).filter((l) => Boolean(l.web_url))
      : [];
  const resultIssues =
    view.kind === "error" || view.kind === "warning" ? (view.issues ?? []) : [];
  const catalogCta = view.kind === "success" ? view.catalogCta : undefined;
  const secondaryCta =
    view.kind === "success" || view.kind === "warning" || view.kind === "error"
      ? view.secondaryCta
      : undefined;

  const resultToneClass =
    view.kind === "success"
      ? resultToneClasses.success
      : view.kind === "warning"
        ? resultToneClasses.warning
        : view.kind === "error"
          ? resultToneClasses.error
          : "";

  const defaultDismissLabel =
    view.kind === "processing"
      ? "Seguir en segundo plano"
      : view.kind === "success"
        ? "Continuar"
        : view.kind === "warning"
          ? "Actualizar estado"
          : "Entendido";

  return (
    <Modal
      titleId={titleId}
      title={view.title}
      descriptionId={descriptionId}
      onClose={onDismiss}
      closeDisabled={processingLocked}
    >
      <div id={descriptionId} className="job-status-modal-body">
        {view.kind === "processing" ? (
          <div
            className="job-status-modal-processing flex items-center gap-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4"
            role="status"
            aria-live="polite"
            aria-busy="true"
          >
            <Spinner size="md" label={view.title} />
            <p className="text-sm text-zinc-600 m-0">
              {view.message || "El sistema está trabajando. Espere un momento…"}
            </p>
          </div>
        ) : (
          <div
            className={cn(
              "job-status-modal-result mt-3 rounded-lg border p-4 text-sm",
              view.kind === "success"
                ? "is-success"
                : view.kind === "warning"
                  ? "is-warning"
                  : view.kind === "error"
                    ? "is-error"
                    : "",
              resultToneClass,
            )}
            role="status"
          >
            <p className="m-0">{view.message}</p>
            {resultIssues.length > 0 ? (
              <ul className="job-status-modal-issues mt-3 list-disc space-y-1 pl-5 text-sm">
                {resultIssues.map((issue) => (
                  <li key={issue.id}>
                    <span className="job-status-modal-issue-message">{issue.message}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {catalogCta ? (
              <ul className="job-status-modal-links mt-3 list-none space-y-2 p-0">
                <li>
                  <Button
                    type="button"
                    variant="outline"
                    className="job-status-modal-catalog-cta w-full justify-start"
                    onClick={catalogCta.onOpen}
                  >
                    {catalogCta.label}
                  </Button>
                </li>
              </ul>
            ) : null}
            {successLinks.length > 0 ? (
              <ul className="job-status-modal-links mt-3 list-none space-y-2 p-0">
                {successLinks.map((link) => (
                  <li key={link.rel}>
                    <Button variant="outline" className="w-full justify-start" asChild>
                      <a href={link.web_url!} target="_blank" rel="noreferrer">
                        {operatorDocumentLabel(link)}
                      </a>
                    </Button>
                  </li>
                ))}
              </ul>
            ) : null}
            {resultLinks.length > 0 ? (
              <ul className="job-status-modal-links mt-3 list-none space-y-2 p-0">
                {resultLinks.map((link) => (
                  <li key={link.rel}>
                    <Button variant="outline" className="w-full justify-start" asChild>
                      <a href={link.web_url!} target="_blank" rel="noreferrer">
                        {operatorDocumentLabel(link)}
                      </a>
                    </Button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )}
      </div>
      {showDismiss ? (
        <div className="modal-actions flex flex-wrap justify-end gap-2 pt-4">
          {secondaryCta ? (
            <Button type="button" variant="secondary" onClick={secondaryCta.onClick}>
              {secondaryCta.label}
            </Button>
          ) : null}
          <Button type="button" variant="default" className="primary" onClick={onDismiss}>
            {view.dismissLabel || defaultDismissLabel}
          </Button>
        </div>
      ) : null}
    </Modal>
  );
}
