import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useProgressiveAsset, isHeavyAssetFile } from "./useProgressiveAsset";

// Mock Tauri invoke
const mockInvoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

describe("isHeavyAssetFile", () => {
  it("detects camera RAW files and HEIC containers correctly", () => {
    expect(isHeavyAssetFile("/photos/DSC_0001.ARW")).toBe(true);
    expect(isHeavyAssetFile("/photos/DSC_0001.cr2")).toBe(true);
    expect(isHeavyAssetFile("/photos/DSC_0001.CR3")).toBe(true);
    expect(isHeavyAssetFile("/photos/DSC_0001.nef")).toBe(true);
    expect(isHeavyAssetFile("/photos/DSC_0001.dng")).toBe(true);
    expect(isHeavyAssetFile("/photos/DSC_0001.heic")).toBe(true);
    expect(isHeavyAssetFile("/photos/DSC_0001.hif")).toBe(true);

    expect(isHeavyAssetFile("/photos/DSC_0001.jpg")).toBe(false);
    expect(isHeavyAssetFile("/photos/DSC_0001.jpeg")).toBe(false);
    expect(isHeavyAssetFile("/photos/DSC_0001.png")).toBe(false);
    expect(isHeavyAssetFile("/photos/DSC_0001.webp")).toBe(false);
  });
});

describe("useProgressiveAsset", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockInvoke.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("handles standard non-heavy files immediately without debouncing or IPC", () => {
    const { result } = renderHook(() => useProgressiveAsset("/photos/DSC_0001.JPG"));

    expect(result.current.displayPath).toBe("/photos/DSC_0001.JPG");
    expect(result.current.rawStatus).toBeNull();
    expect(result.current.isHeavy).toBe(false);
    expect(mockInvoke).not.toHaveBeenCalled();
  });

  it("extracts fast preview immediately and debounces full demosaic on settle", async () => {
    mockInvoke.mockImplementation(async (cmd: string, args: { path: string }) => {
      if (cmd === "resolve_photo_preview") {
        return `/cache/fast_${args.path.split("/").pop()}.jpg`;
      }
      if (cmd === "resolve_full_raw_render") {
        return `/cache/full_${args.path.split("/").pop()}.jpg`;
      }
      return null;
    });

    const { result } = renderHook(() => useProgressiveAsset("/photos/DSC_1000.ARW", 300));

    expect(result.current.isHeavy).toBe(true);
    expect(result.current.rawStatus).toBe("loading");

    // Fast preview extraction should be dispatched immediately
    expect(mockInvoke).toHaveBeenCalledWith("resolve_photo_preview", {
      path: "/photos/DSC_1000.ARW",
    });
    // Stage 2 full demosaic should NOT be dispatched yet
    expect(mockInvoke).not.toHaveBeenCalledWith("resolve_full_raw_render", expect.anything());

    // Resolve stage 1 promise
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.displayPath).toBe("/cache/fast_DSC_1000.ARW.jpg");
    expect(result.current.rawStatus).toBe("fast");

    // Advance timers past debounce threshold (300ms)
    await act(async () => {
      vi.advanceTimersByTime(300);
      await Promise.resolve();
    });

    // Now Stage 2 full demosaic must have been invoked
    expect(mockInvoke).toHaveBeenCalledWith("resolve_full_raw_render", {
      path: "/photos/DSC_1000.ARW",
    });

    // Wait for stage 2 to finish
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.displayPath).toBe("/cache/full_DSC_1000.ARW.jpg");
    expect(result.current.rawStatus).toBe("full");
  });

  it("cancels Stage 2 heavy render when switching photos rapidly", async () => {
    mockInvoke.mockImplementation(async (cmd: string, args: { path: string }) => {
      if (cmd === "resolve_photo_preview") {
        return `/cache/fast_${args.path.split("/").pop()}.jpg`;
      }
      if (cmd === "resolve_full_raw_render") {
        return `/cache/full_${args.path.split("/").pop()}.jpg`;
      }
      return null;
    });

    const { rerender } = renderHook(
      ({ path }) => useProgressiveAsset(path, 300),
      { initialProps: { path: "/photos/DSC_2001.ARW" } }
    );

    // Rapid switch after 50ms to second photo
    act(() => {
      vi.advanceTimersByTime(50);
    });
    rerender({ path: "/photos/DSC_2002.ARW" });

    // Rapid switch after another 50ms to third photo
    act(() => {
      vi.advanceTimersByTime(50);
    });
    rerender({ path: "/photos/DSC_2003.ARW" });

    // Full demosaic should NEVER have been called for DSC_2001 or DSC_2002!
    const fullCalls = mockInvoke.mock.calls.filter((call) => call[0] === "resolve_full_raw_render");
    expect(fullCalls).toHaveLength(0);

    // Let the third photo settle for >= 300ms
    await act(async () => {
      vi.advanceTimersByTime(300);
      await Promise.resolve();
    });

    // Only DSC_2003 was requested for full demosaic
    expect(mockInvoke).toHaveBeenCalledWith("resolve_full_raw_render", {
      path: "/photos/DSC_2003.ARW",
    });
  });
});
