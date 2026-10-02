import type {
  ExclusionReasonCode,
  UiMergeAsiento,
  UiMergeGroup,
  UiMergePaymentKind,
  UiMergeVerification,
  UnusedAsientoReasonCode,
} from "../types/contract";
import { formatCop } from "./amortizationDecisions";

/** Cada handler resuelve null si se guardó, o el mensaje de error para el operador. */
export type MergeDecisionHandlers = {
  onExclude: (credit: string, motivo: ExclusionReasonCode, nota: string) => Promise<string | null>;
  onUndoExclude: (credit: string) => Promise<string | null>;
  onConfirm: (conciliationKey: string, nota: string) => Promise<string | null>;
  onUndoConfirm: (conciliationKey: string) => Promise<string | null>;
  onAssign: (
    groupKey: string,
    items: Array<{ asiento_path: string; id_pago: string }>,
  ) => Promise<string | null>;
  onUndoAssign: (groupKey: string) => Promise<string | null>;
  onMarkUnused: (asientoPath: string, motivo: UnusedAsientoReasonCode) => Promise<string | null>;
  onUndoUnused: (asientoPath: string) => Promise<string | null>;
  onVerify: () => void;
};

/** «2026-09-22» → «22/09». */
export function shortDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  return m ? `${m[3]}/${m[2]}` : String(iso ?? "");
}

export function groupCreditsLabel(group: Pick<UiMergeGroup, "credits">): string {
  return group.credits.join(" y ");
}

export function groupClientLabel(group: Pick<UiMergeGroup, "cliente" | "clientes" | "credits">): string {
  if (group.cliente) return group.cliente;
  const names = [...new Set(group.credits.map((c) => group.clientes[c]).filter(Boolean))];
  return names.join(", ");
}

export function motivosLine(group: Pick<UiMergeGroup, "motivos">): string {
  return group.motivos.map((m) => m.label).join(" · ");
}

export function attentionGroups(v: UiMergeVerification | null | undefined): UiMergeGroup[] {
  return (v?.groups ?? []).filter((g) => g.status === "attention");
}

export function excludedGroups(v: UiMergeVerification | null | undefined): UiMergeGroup[] {
  return (v?.groups ?? []).filter((g) => g.status === "excluded");
}

const STATUS_ORDER: Record<UiMergeGroup["status"], number> = { attention: 0, ready: 1, excluded: 2 };

/** Todos los créditos: primero los que requieren atención, luego listos y al final excluidos. */
export function orderedGroups(v: UiMergeVerification | null | undefined): UiMergeGroup[] {
  return (v?.groups ?? [])
    .map((g, i) => ({ g, i }))
    .sort((a, b) => (STATUS_ORDER[a.g.status] ?? 1) - (STATUS_ORDER[b.g.status] ?? 1) || a.i - b.i)
    .map(({ g }) => g);
}

export type StatusChipTone = "ok" | "warn" | "danger" | "muted";

export interface StatusChip {
  label: string;
  tone: StatusChipTone;
}

const DANGER_MOTIVOS = new Set([
  "FALTA_ASIENTO",
  "ASIENTO_ILEGIBLE",
  "ASIENTO_SIN_VALORES",
  "FALTA_EXTRACTO",
  "FALTA_DOCUMENTO",
]);

const CHIP_LABELS: Record<string, string> = { ASIGNAR_ASIENTOS: "Asignar asientos" };

/** Estado del crédito en palabras, con color: verde listo, rojo falta o ilegible, ámbar por revisar, gris excluido. */
export function groupStatusChips(group: Pick<UiMergeGroup, "status" | "motivos">): StatusChip[] {
  if (group.status === "ready") return [{ label: "Listo", tone: "ok" }];
  if (group.status === "excluded") return [{ label: "Excluido", tone: "muted" }];
  if (group.motivos.length === 0) return [{ label: "Revisar", tone: "warn" }];
  return group.motivos.map((m) => ({
    label: CHIP_LABELS[m.code] ?? m.label,
    tone: DANGER_MOTIVOS.has(m.code) ? "danger" : "warn",
  }));
}

export function verificationSummary(v: UiMergeVerification): string {
  return `${v.credits_ready} de ${v.credits_total} créditos listos para consolidar.`;
}

/** Texto de la confirmación de Consolidar. */
export function mergeConfirmSentence(v: UiMergeVerification): string {
  const n = v.consolidados;
  const head = n === 1 ? "Se generará 1 consolidado." : `Se generarán ${n} consolidados.`;
  return `${head} Excluidos: ${v.credits_excluded}`;
}

export function excludedCreditsList(v: UiMergeVerification): string | null {
  if (!v.excluded.length) return null;
  return v.excluded
    .map((e) => (e.cliente ? `crédito ${e.credito} · ${e.cliente}` : `crédito ${e.credito}`))
    .join(", ");
}

/** Motivo del «No corresponde a este pago» según lo que muestra la verificación. */
export function unusedReasonFor(asiento: Pick<UiMergeAsiento, "state">): UnusedAsientoReasonCode {
  if (asiento.state === "otro_credito") return "OTRO_CREDITO";
  if (asiento.state === "pago_anterior") return "PAGO_ANTERIOR";
  return "NO_CORRESPONDE";
}

export type AssignmentSelection = Record<string, string>;

export function assignableAsientos(group: UiMergeGroup): UiMergeAsiento[] {
  return group.asientos.filter((a) => a.state === "usable");
}

/** Asignación inicial: la vigente, si no la propuesta (sin propuesta en empate). */
export function initialSelection(group: UiMergeGroup): AssignmentSelection {
  const out: AssignmentSelection = {};
  const proposal = group.assignment?.proposal ?? {};
  for (const a of assignableAsientos(group)) {
    const current = group.assignment?.explicit ? a.assigned_id_pago : null;
    const pick = current || proposal[a.path] || "";
    if (pick && a.eligible_id_pagos.includes(pick)) out[a.path] = pick;
  }
  return out;
}

export type PaymentAssignmentStatus = "cuadra" | "faltan" | "sobran";

export interface PaymentAssignmentLine {
  id_pago: string;
  fecha: string;
  monto: number;
  asignado: number;
  status: PaymentAssignmentStatus;
  diferencia: number;
  text: string;
}

function cents(n: number | null | undefined): number {
  return Math.round((n ?? 0) * 100);
}

export function paymentAssignmentLines(
  group: UiMergeGroup,
  selection: AssignmentSelection,
): PaymentAssignmentLine[] {
  const byPath = new Map(assignableAsientos(group).map((a) => [a.path, a]));
  return (group.assignment?.payments ?? []).map((p) => {
    let assigned = 0;
    for (const [path, pid] of Object.entries(selection)) {
      if (pid === p.id_pago) assigned += cents(byPath.get(path)?.cash);
    }
    const bank = cents(p.monto);
    const diff = Math.abs(bank - assigned) / 100;
    const status: PaymentAssignmentStatus =
      assigned === bank ? "cuadra" : assigned < bank ? "faltan" : "sobran";
    const tail =
      status === "cuadra"
        ? "Cuadra"
        : status === "faltan"
          ? `Faltan ${formatCop(diff)}`
          : `Sobran ${formatCop(diff)}`;
    return {
      id_pago: p.id_pago,
      fecha: p.fecha,
      monto: bank / 100,
      asignado: assigned / 100,
      status,
      diferencia: diff,
      text: `Pago ${shortDate(p.fecha)} ${formatCop(bank / 100)} · Asignado ${formatCop(assigned / 100)} · ${tail}`,
    };
  });
}

/** Confirmar: todos los asientos asignados y ningún pago con más de lo recibido. */
export function canConfirmAssignment(group: UiMergeGroup, selection: AssignmentSelection): boolean {
  const usable = assignableAsientos(group);
  if (usable.length === 0) return false;
  const complete = usable.every(
    (a) => Boolean(selection[a.path]) && a.eligible_id_pagos.includes(selection[a.path]),
  );
  if (!complete) return false;
  return paymentAssignmentLines(group, selection).every((l) => l.status !== "sobran");
}

export function hasShortfall(group: UiMergeGroup, selection: AssignmentSelection): boolean {
  return paymentAssignmentLines(group, selection).some((l) => l.status === "faltan");
}

const KIND_LABEL: Record<UiMergePaymentKind, string> = { pago: "Pago", abono: "Abono" };

export function paymentLabel(group: UiMergeGroup, idPago: string): string {
  const p = group.assignment?.payments.find((x) => x.id_pago === idPago);
  if (!p) return idPago;
  return p.kind ? `${KIND_LABEL[p.kind]} · ${p.label}` : p.label;
}

/** «2026-09-15» → «15/09/2026». */
export function longDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  return m ? `${m[3]}/${m[2]}/${m[1]}` : String(iso ?? "");
}

/** El crédito tiene consignaciones de más de una fecha (cada asiento va a un pago). */
export function hasSeveralPaymentDates(group: Pick<UiMergeGroup, "consignaciones">): boolean {
  return new Set(group.consignaciones.map((c) => c.fecha).filter(Boolean)).size > 1;
}

/** Pago al que va el asiento: «Pago del 15/09/2026» o «Abono del 30/09/2026». */
export function assignedPaymentText(
  group: Pick<UiMergeGroup, "consignaciones">,
  idPago: string | null | undefined,
): string {
  const c = idPago ? group.consignaciones.find((x) => x.id_pago === idPago) : undefined;
  if (!c) return "—";
  return `${c.kind === "abono" ? "Abono" : "Pago"} del ${longDate(c.fecha)}`;
}

/** Botón de asignación: «Asignar» solo si falta asignar; si ya hay una (automática o del operador), «Modificar». */
export function assignmentButtonLabel(group: Pick<UiMergeGroup, "assignment">): string {
  const a = group.assignment;
  return a?.required && !a.explicit ? "Asignar asientos a sus pagos" : "Modificar asignación";
}

export const MSG_TIE =
  "Hay más de una asignación que cuadra. Revise los PDF antes de confirmar.";

export const MSG_IMPOSSIBLE =
  "Probablemente un asiento cubre pagos de dos fechas. Solicite a Contabilidad separarlo y reemplácelo, o excluya el crédito.";

export const MSG_SHORTFALL =
  "Lo que falte en un pago quedará registrado como «Diferencia no aplicada».";
