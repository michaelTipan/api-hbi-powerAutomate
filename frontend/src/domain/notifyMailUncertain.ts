/** Checkpoint F-02: NotifyIdempotencyKey / job sin confirmación de sendMail. */

export const NOTIFY_SENDING_KEY_PREFIX = "NOTIFY_SENDING|";

export function isNotifySendingIdempotencyKey(
  key: string | null | undefined,
): boolean {
  return (key || "").trim().toUpperCase().startsWith(NOTIFY_SENDING_KEY_PREFIX);
}

export function isDurableNotifySuccessKey(
  key: string | null | undefined,
  processKey: string | null | undefined,
): boolean {
  const k = (key || "").trim();
  const pk = (processKey || "").trim();
  if (!k || isNotifySendingIdempotencyKey(k)) return false;
  if (pk && k !== pk) return false;
  return true;
}

export function isNotifyMailUncertainJob(job: {
  result_summary?: Record<string, unknown> | null;
}): boolean {
  const summary = job.result_summary;
  if (!summary || typeof summary !== "object") return false;
  const err = String(summary.merge_control_error_code || "")
    .trim()
    .toLowerCase();
  const warning = String(summary.merge_control_warning || "")
    .trim()
    .toLowerCase();
  const status = String(summary.status || "").trim().toLowerCase();
  return (
    err === "notify_mail_uncertain" ||
    warning === "notify_mail_uncertain" ||
    status === "notify_mail_uncertain"
  );
}
