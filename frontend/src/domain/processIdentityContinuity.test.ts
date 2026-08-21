import { afterEach, describe, expect, it } from "vitest";
import { UiApiError } from "../api/errors";
import {
  GENERATE_IDENTITY_FOLLOW_STORAGE_KEY,
  bankCodeFromProcessKey,
  clearGenerateIdentityFollow,
  isProcessNotFoundError,
  processKeyFromUiJob,
  readGenerateIdentityFollow,
  resolveActiveSuccessorKey,
  shouldResumeGenerateIdentityFollow,
  writeGenerateIdentityFollow,
} from "./processIdentityContinuity";

afterEach(() => {
  clearGenerateIdentityFollow();
});

describe("bankCodeFromProcessKey", () => {
  it("extrae banco válido", () => {
    expect(
      bankCodeFromProcessKey(
        "payment-validation|banco_bancolombia|2026-08-21|ea9d9860-920b-46b8-b108-a2cf77aa1111",
      ),
    ).toBe("banco_bancolombia");
  });

  it("rechaza formas inválidas", () => {
    expect(bankCodeFromProcessKey("foo")).toBeNull();
    expect(
      bankCodeFromProcessKey("payment-validation|otro|2026-08-21|uuid"),
    ).toBeNull();
  });
});

describe("resolveActiveSuccessorKey", () => {
  it("devuelve el proceso vivo del mismo banco si la clave murió", () => {
    const stale =
      "payment-validation|banco_bancolombia|2026-08-21|old-uuid";
    const live =
      "payment-validation|banco_bancolombia|2026-08-21|new-uuid";
    expect(
      resolveActiveSuccessorKey({
        staleProcessKey: stale,
        banks: [
          {
            bank_code: "banco_bancolombia",
            active_process_key: live,
          },
          {
            bank_code: "banco_bogota",
            active_process_key: "payment-validation|banco_bogota|2026-08-01|x",
          },
        ],
      }),
    ).toBe(live);
  });

  it("no redirige si no hay activo o es la misma clave", () => {
    const key = "payment-validation|banco_bogota|2026-08-21|same";
    expect(
      resolveActiveSuccessorKey({
        staleProcessKey: key,
        banks: [{ bank_code: "banco_bogota", active_process_key: key }],
      }),
    ).toBeNull();
    expect(
      resolveActiveSuccessorKey({
        staleProcessKey: key,
        banks: [{ bank_code: "banco_bogota", active_process_key: null }],
      }),
    ).toBeNull();
  });

  it("no cruza de banco", () => {
    expect(
      resolveActiveSuccessorKey({
        staleProcessKey: "payment-validation|banco_bogota|2026-08-21|old",
        banks: [
          {
            bank_code: "banco_bancolombia",
            active_process_key:
              "payment-validation|banco_bancolombia|2026-08-21|live",
          },
        ],
      }),
    ).toBeNull();
  });
});

describe("isProcessNotFoundError", () => {
  it("detecta UiApiError process_not_found", () => {
    expect(
      isProcessNotFoundError(
        new UiApiError({
          status: 404,
          errorCode: "process_not_found",
          userMessage: "No se encontró el proceso solicitado.",
        }),
      ),
    ).toBe(true);
  });

  it("ignora otros 404", () => {
    expect(
      isProcessNotFoundError(
        new UiApiError({
          status: 404,
          errorCode: "other",
          userMessage: "No encontrado",
        }),
      ),
    ).toBe(false);
  });
});

describe("processKeyFromUiJob", () => {
  it("prioriza process_key del job y luego result_summary", () => {
    expect(
      processKeyFromUiJob({
        process_key: "pk-job",
        result_summary: { process_key: "pk-sum" },
      }),
    ).toBe("pk-job");
    expect(
      processKeyFromUiJob({
        process_key: null,
        result_summary: { process_key: "pk-sum" },
      }),
    ).toBe("pk-sum");
  });
});

describe("generate identity follow storage", () => {
  it("persiste y reanuda solo el mismo job generate en vuelo", () => {
    writeGenerateIdentityFollow({
      jobId: "job-1",
      bankCode: "banco_bancolombia",
      startedAt: Date.now(),
    });
    const follow = readGenerateIdentityFollow();
    expect(follow?.jobId).toBe("job-1");
    expect(
      shouldResumeGenerateIdentityFollow({
        follow,
        jobId: "job-1",
        jobType: "generate",
        jobStatus: "running",
        bankCode: "banco_bancolombia",
      }),
    ).toBe(true);
    expect(
      shouldResumeGenerateIdentityFollow({
        follow,
        jobId: "job-other",
        jobType: "generate",
        jobStatus: "running",
        bankCode: "banco_bancolombia",
      }),
    ).toBe(false);
    expect(
      shouldResumeGenerateIdentityFollow({
        follow,
        jobId: "job-1",
        jobType: "generate",
        jobStatus: "completed",
        bankCode: "banco_bancolombia",
      }),
    ).toBe(false);
  });

  it("usa la clave de storage canónica", () => {
    writeGenerateIdentityFollow({
      jobId: "j",
      bankCode: "banco_bogota",
      startedAt: Date.now(),
    });
    expect(sessionStorage.getItem(GENERATE_IDENTITY_FOLLOW_STORAGE_KEY)).toBeTruthy();
  });
});
