import { describe, it, expect, vi, beforeEach } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import {
  initDebugLogger,
  isDebugTimingEnabled,
  logRenderTiming,
  logDebugEvent,
  setDebugEnabledForTesting,
} from "./debugLogger";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async () => false),
}));

describe("debugLogger", () => {
  beforeEach(() => {
    setDebugEnabledForTesting(false);
    vi.clearAllMocks();
  });

  it("writes nothing in a normal run when debug mode is disabled", async () => {
    vi.mocked(invoke).mockResolvedValueOnce(false);
    const enabled = await initDebugLogger();
    expect(enabled).toBe(false);
    expect(isDebugTimingEnabled()).toBe(false);

    logRenderTiming("render.preview.display", 14.5, { stem: "DSC_0001" });
    logDebugEvent("navigation", { index: 1 });

    // Only get_debug_status was called; record_debug_event was never invoked
    expect(invoke).toHaveBeenCalledTimes(1);
    expect(invoke).toHaveBeenCalledWith("get_debug_status");
  });

  it("records render timings with durationMs and events when debug mode is enabled", async () => {
    vi.mocked(invoke).mockResolvedValueOnce(true);
    const enabled = await initDebugLogger();
    expect(enabled).toBe(true);

    logRenderTiming("render.split_comparison", 18.2, { primary: "DSC_0001" });
    logDebugEvent("zoom", { scale: 2.0 }, 1.2);

    expect(invoke).toHaveBeenCalledWith("record_debug_event", {
      event: "render.split_comparison",
      category: "render",
      durationMs: 18.2,
      details: { primary: "DSC_0001" },
    });
    expect(invoke).toHaveBeenCalledWith("record_debug_event", {
      event: "zoom",
      category: "event",
      durationMs: 1.2,
      details: { scale: 2.0 },
    });
  });
});
