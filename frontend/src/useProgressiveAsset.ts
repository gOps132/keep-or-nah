import { useState, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

export const HEAVY_EXTENSIONS = new Set([
  ".arw",
  ".cr2",
  ".cr3",
  ".nef",
  ".nrw",
  ".dng",
  ".orf",
  ".rw2",
  ".pef",
  ".raf",
  ".srw",
  ".heic",
  ".heif",
  ".hif",
  ".avif",
  ".jxl",
  ".psd",
]);

// Dynamically sync registered heavy extensions from Rust core
if (typeof window !== "undefined") {
  try {
    const res = invoke<string[]>("get_supported_heavy_extensions");
    if (res && typeof res.then === "function") {
      res
        .then((exts) => {
          if (Array.isArray(exts)) {
            exts.forEach((ext) => {
              HEAVY_EXTENSIONS.add(
                ext.toLowerCase().startsWith(".") ? ext.toLowerCase() : `.${ext.toLowerCase()}`
              );
            });
          }
        })
        .catch(() => {
          // Fallback to default set
        });
    }
  } catch {
    // Fallback to default set
  }
}

export function isHeavyAssetFile(path: string): boolean {
  const dotIndex = path.lastIndexOf(".");
  if (dotIndex === -1) return false;
  return HEAVY_EXTENSIONS.has(path.slice(dotIndex).toLowerCase());
}

export type RawAssetStatus = "fast" | "full" | "loading" | null;

export interface ProgressiveAssetResult {
  displayPath: string | null;
  rawStatus: RawAssetStatus;
  isHeavy: boolean;
}

// Module-level caches across renders so previously resolved assets are retained
const fastPreviewCache: Record<string, string> = {};
const fullRenderCache: Record<string, string> = {};

/**
 * Custom hook managing progressive 2-stage asset loading:
 * Stage 1: Fast embedded preview / thumbnail (<15ms)
 * Stage 2: Background heavy demosaic / render, debounced on user settle (300ms default)
 */
export function useProgressiveAsset(
  activePath: string | null,
  debounceMs = 300
): ProgressiveAssetResult {
  const activePathRef = useRef(activePath);
  activePathRef.current = activePath;

  const [displayPath, setDisplayPath] = useState<string | null>(() => {
    if (!activePath) return null;
    if (!isHeavyAssetFile(activePath)) return activePath;
    return fullRenderCache[activePath] || fastPreviewCache[activePath] || activePath;
  });

  const [rawStatus, setRawStatus] = useState<RawAssetStatus>(() => {
    if (!activePath || !isHeavyAssetFile(activePath)) return null;
    if (fullRenderCache[activePath]) return "full";
    if (fastPreviewCache[activePath]) return "fast";
    return "loading";
  });

  const isHeavy = activePath ? isHeavyAssetFile(activePath) : false;

  useEffect(() => {
    if (!activePath) {
      setDisplayPath(null);
      setRawStatus(null);
      return;
    }

    if (!isHeavyAssetFile(activePath)) {
      setDisplayPath(activePath);
      setRawStatus(null);
      return;
    }

    // If full render already cached, show it immediately
    if (fullRenderCache[activePath]) {
      setDisplayPath(fullRenderCache[activePath]);
      setRawStatus("full");
      return;
    }

    // Set initial display to fast preview if cached, or fallback to source path
    const cachedFast = fastPreviewCache[activePath];
    if (cachedFast) {
      setDisplayPath(cachedFast);
      setRawStatus("fast");
    } else {
      setDisplayPath(activePath);
      setRawStatus("loading");

      // Stage 1: Resolve fast preview immediately (<15ms)
      invoke<string>("resolve_photo_preview", { path: activePath })
        .then((fastPath) => {
          if (fastPath) {
            fastPreviewCache[activePath] = fastPath;
          }
          if (activePathRef.current === activePath) {
            setDisplayPath(fastPath || activePath);
            setRawStatus((prev) => (prev === "full" ? "full" : "fast"));
          }
        })
        .catch((err) => {
          console.warn("Fast preview extraction failed:", err);
          if (activePathRef.current === activePath) {
            setRawStatus((prev) => (prev === "full" ? "full" : "fast"));
          }
        });
    }

    // Stage 2: Settle detection via debounce before invoking heavy render
    let isCancelled = false;
    const timer = setTimeout(() => {
      if (isCancelled || activePathRef.current !== activePath) return;

      setRawStatus("loading");
      invoke<string>("resolve_full_raw_render", { path: activePath })
        .then((fullPath) => {
          if (isCancelled || activePathRef.current !== activePath) return;
          if (fullPath) {
            fullRenderCache[activePath] = fullPath;
            setDisplayPath(fullPath);
            setRawStatus("full");
          }
        })
        .catch((err) => {
          if (isCancelled || activePathRef.current !== activePath) return;
          console.warn("Heavy render unavailable or cancelled, keeping fast preview:", err);
          setRawStatus("fast");
        });
    }, debounceMs);

    return () => {
      isCancelled = true;
      clearTimeout(timer);
    };
  }, [activePath, debounceMs]);

  return {
    displayPath,
    rawStatus,
    isHeavy,
  };
}
