import { vi } from "vitest";
import type {
  UiMergeAsiento,
  UiMergeAssignment,
  UiMergeFecha,
  UiMergeGroup,
  UiMergePayment,
  UiMergeVerification,
} from "../types/contract";
import type { MergeDecisionHandlers } from "../domain/mergeVerification";

/** Datos sintéticos para pruebas de la fase Consolidar (sin datos reales). */
export function asiento(overrides: Partial<UiMergeAsiento> = {}): UiMergeAsiento {
  return {
    path: "ASIENTOS/102/A-1.pdf",
    name: "A-1.pdf",
    credito: "102",
    numero: "1001",
    fecha: "2026-09-22",
    cash: 100,
    capital: 80,
    intereses: 20,
    mora: 0,
    retenciones: null,
    saldos_menores: null,
    web_url: "https://example.com/a-1.pdf",
    state: "usable",
    state_label: "",
    assigned_id_pago: null,
    eligible_id_pagos: ["P1"],
    can_mark_unused: true,
    can_undo_unused: false,
    ...overrides,
  };
}

export function payment(overrides: Partial<UiMergePayment> = {}): UiMergePayment {
  return {
    id_pago: "P1",
    fecha: "2026-09-22",
    monto: 100,
    label: "22/09 · $100",
    ...overrides,
  };
}

export function assignment(overrides: Partial<UiMergeAssignment> = {}): UiMergeAssignment {
  return {
    required: true,
    explicit: false,
    proposal: {},
    tie: false,
    impossible: false,
    payments: [payment()],
    can_undo: false,
    ...overrides,
  };
}

export function fecha(overrides: Partial<UiMergeFecha> = {}): UiMergeFecha {
  return {
    fecha: "2026-09-22",
    monto_banco: 100,
    monto_asientos: 100,
    diferencia: 0,
    conciliation_key: "102|2026-09-22",
    status: "OK",
    confirmation: null,
    ...overrides,
  };
}

export function group(overrides: Partial<UiMergeGroup> = {}): UiMergeGroup {
  return {
    group_key: "102",
    credits: ["102"],
    credit_labels: { "102": "102" },
    clientes: { "102": "CLIENTE SINTETICO" },
    cliente: "CLIENTE SINTETICO",
    tablas: {},
    folders: [{ credito: "102", path: "ASIENTOS/102" }],
    consignaciones: [
      {
        id_pago: "P1",
        fecha: "2026-09-22",
        monto: 100,
        concepto: "ABONO CREDITO",
        tipo: "PAGO",
        credits: ["102"],
        label: "22/09 · $100",
      },
    ],
    consignado: 100,
    status: "ready",
    motivos: [],
    primary_action: null,
    segun_asientos: 100,
    pendiente: 0,
    asientos: [asiento()],
    fechas: [fecha()],
    assignment: null,
    tipo: null,
    exclusion: null,
    actions: {
      continuar: false,
      no_corresponde: true,
      asignar: false,
      tipo: false,
      excluir: false,
    },
    has_retenciones: false,
    has_saldos_menores: false,
    ...overrides,
  };
}

/** Pagos en dos fechas: 22/09 $100 y 25/09 $50; asientos de $100 y $50. */
export function twoPaymentGroup(overrides: Partial<UiMergeGroup> = {}): UiMergeGroup {
  return group({
    group_key: "133",
    credits: ["133"],
    credit_labels: { "133": "133" },
    clientes: { "133": "CLIENTE DOS FECHAS" },
    cliente: "CLIENTE DOS FECHAS",
    status: "attention",
    motivos: [{ code: "ASIGNAR_ASIENTOS", label: "Asignar asientos a sus pagos" }],
    primary_action: "asignar",
    consignado: 150,
    segun_asientos: 150,
    pendiente: 0,
    consignaciones: [
      {
        id_pago: "P1",
        fecha: "2026-09-22",
        monto: 100,
        concepto: "ABONO",
        tipo: "PAGO",
        credits: ["133"],
        label: "22/09 · $100",
      },
      {
        id_pago: "P2",
        fecha: "2026-09-25",
        monto: 50,
        concepto: "ABONO",
        tipo: "PAGO",
        credits: ["133"],
        label: "25/09 · $50",
      },
    ],
    asientos: [
      asiento({
        path: "ASIENTOS/133/A.pdf",
        name: "A.pdf",
        credito: "133",
        numero: "2001",
        fecha: "2026-09-26",
        cash: 100,
        eligible_id_pagos: ["P1", "P2"],
      }),
      asiento({
        path: "ASIENTOS/133/B.pdf",
        name: "B.pdf",
        credito: "133",
        numero: "2002",
        fecha: "2026-09-26",
        cash: 50,
        eligible_id_pagos: ["P1", "P2"],
      }),
    ],
    fechas: [
      fecha({ fecha: "2026-09-22", monto_banco: 100, monto_asientos: 100, conciliation_key: "133|2026-09-22" }),
      fecha({ fecha: "2026-09-25", monto_banco: 50, monto_asientos: 50, conciliation_key: "133|2026-09-25" }),
    ],
    assignment: assignment({
      proposal: { "ASIENTOS/133/A.pdf": "P1", "ASIENTOS/133/B.pdf": "P2" },
      payments: [
        payment({ id_pago: "P1", fecha: "2026-09-22", monto: 100, label: "22/09 · $100" }),
        payment({ id_pago: "P2", fecha: "2026-09-25", monto: 50, label: "25/09 · $50" }),
      ],
    }),
    actions: {
      continuar: false,
      no_corresponde: true,
      asignar: true,
      tipo: false,
      excluir: true,
    },
    ...overrides,
  });
}

export function verification(
  groups: UiMergeGroup[],
  overrides: Partial<UiMergeVerification> = {},
): UiMergeVerification {
  const excluded = groups.filter((g) => g.status === "excluded");
  const credits = (st: UiMergeGroup["status"]) =>
    groups.filter((g) => g.status === st).reduce((n, g) => n + g.credits.length, 0);
  return {
    groups,
    credits_total: groups.reduce((n, g) => n + g.credits.length, 0),
    credits_ready: credits("ready"),
    credits_excluded: credits("excluded"),
    credits_attention: credits("attention"),
    consolidados: groups.filter((g) => g.status !== "excluded").length,
    excluded: excluded.flatMap((g) =>
      g.credits.map((c) => ({ credito: c, cliente: g.clientes[c] ?? "", motivo: g.exclusion?.motivo ?? "" })),
    ),
    all_excluded: groups.length > 0 && excluded.length === groups.length,
    unused_asientos: [],
    active_exclusions: excluded.length,
    ...overrides,
  };
}

export function handlers(overrides: Partial<MergeDecisionHandlers> = {}): MergeDecisionHandlers {
  const ok = () => vi.fn().mockResolvedValue(null);
  return {
    onExclude: ok(),
    onUndoExclude: ok(),
    onConfirm: ok(),
    onUndoConfirm: ok(),
    onAssign: ok(),
    onUndoAssign: ok(),
    onMarkUnused: ok(),
    onUndoUnused: ok(),
    onUseTipo: ok(),
    onUndoTipo: ok(),
    onVerify: vi.fn(),
    ...overrides,
  };
}
