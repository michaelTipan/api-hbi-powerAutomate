import { describe, expect, it } from "vitest";
import {
  isDurableNotifySuccessKey,
  isNotifyMailUncertainJob,
  isNotifySendingIdempotencyKey,
} from "./notifyMailUncertain";

describe("notifyMailUncertain", () => {
  const pk = "payment-validation|banco_bogota|2026-07-30|abc";

  it("reconoce NOTIFY_SENDING|<process_key> y no lo trata como éxito durable", () => {
    expect(isNotifySendingIdempotencyKey(`NOTIFY_SENDING|${pk}`)).toBe(true);
    expect(isDurableNotifySuccessKey(`NOTIFY_SENDING|${pk}`, pk)).toBe(false);
    expect(isDurableNotifySuccessKey(pk, pk)).toBe(true);
    expect(isDurableNotifySuccessKey("otro", pk)).toBe(false);
  });

  it("detecta job notify_mail_uncertain", () => {
    expect(
      isNotifyMailUncertainJob({
        result_summary: { merge_control_error_code: "notify_mail_uncertain" },
      }),
    ).toBe(true);
    expect(isNotifyMailUncertainJob({ result_summary: { status: "ok" } })).toBe(false);
  });
});
