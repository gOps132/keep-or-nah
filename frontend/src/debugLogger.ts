import { invoke } from "@tauri-apps/api/core";

let debugEnabled = false;

export function isDebugTimingEnabled(): boolean {
  return debugEnabled;
}

export function setDebugEnabledForTesting(enabled: boolean): void {
  debugEnabled = enabled;
}

export async function initDebugLogger(): Promise<boolean> {
  try {
    const status = await invoke<boolean>("get_debug_status");
    debugEnabled = Boolean(status);
  } catch {
    debugEnabled = false;
  }
  return debugEnabled;
}

export function logRenderTiming(
  event: string,
  durationMs: number,
  details?: Record<string, unknown>
): void {
  if (!debugEnabled) return;
  invoke("record_debug_event", {
    event,
    category: "render",
    durationMs,
    details: details ?? {},
  }).catch(() => {});
}

export function logDebugEvent(
  event: string,
  details?: Record<string, unknown>,
  durationMs?: number
): void {
  if (!debugEnabled) return;
  invoke("record_debug_event", {
    event,
    category: "event",
    durationMs: durationMs ?? null,
    details: details ?? {},
  }).catch(() => {});
}
