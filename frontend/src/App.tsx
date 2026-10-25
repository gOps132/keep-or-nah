import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { FolderOpen, Sparkles } from "lucide-react";
import { PhotoGroup, ThumbnailData, ExifMetadataDto } from "./types";
import { PhotoStrip } from "./PhotoStrip";
import { PreviewViewport } from "./PreviewViewport";
import { ActionHud } from "./ActionHud";

export default function App() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [photoGroups, setPhotoGroups] = useState<PhotoGroup[]>([]);
  const [activeIndex, setActiveIndex] = useState<number>(0);
  const [thumbnails, setThumbnails] = useState<Record<string, ThumbnailData>>({});
  const [exifCache, setExifCache] = useState<Record<string, ExifMetadataDto>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [bestShotStems, setBestShotStems] = useState<Set<string>>(new Set());

  // Load directory items and trigger scan
  const loadFolder = useCallback(async (folderPath: string) => {
    try {
      setIsLoading(true);
      setSelectedFolder(folderPath);
      const groups = await invoke<PhotoGroup[]>("scan_directory", { path: folderPath });
      setPhotoGroups(groups);
      setActiveIndex(0);
      setThumbnails({});
      setExifCache({});

      // Background thumbnail loading loop
      for (const group of groups) {
        invoke<ThumbnailData>("get_thumbnail", {
          path: group.representative,
          maxEdge: 160,
        })
          .then((thumb) => {
            setThumbnails((prev) => ({
              ...prev,
              [group.representative]: thumb,
            }));
          })
          .catch((err) => {
            console.error(`Failed to load thumbnail for ${group.representative}:`, err);
          });
      }
    } catch (err) {
      console.error("Failed to scan directory:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleOpenFolder = async () => {
    try {
      const folderPath = await invoke<string | null>("open_directory_dialog");
      if (folderPath) {
        await loadFolder(folderPath);
      }
    } catch (err) {
      console.error("Failed to open directory dialog:", err);
    }
  };

  const activeGroup = photoGroups[activeIndex] ?? null;

  // Load EXIF metadata for active photo
  useEffect(() => {
    if (!activeGroup) return;

    if (!exifCache[activeGroup.representative]) {
      invoke<ExifMetadataDto>("read_exif_metadata", {
        path: activeGroup.representative,
      })
        .then((exif) => {
          setExifCache((prev) => ({
            ...prev,
            [activeGroup.representative]: exif,
          }));
        })
        .catch((err) => {
          console.error("Failed to read EXIF:", err);
        });
    }
  }, [activeGroup, exifCache]);

  // Keyboard navigation & triage action shortcuts (1, 2, F)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (photoGroups.length === 0) return;

      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setActiveIndex((prev) => Math.max(0, prev - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1));
      } else if (e.key === "1") {
        e.preventDefault();
        // Keep shortcut: advance to next
        setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1));
      } else if (e.key === "2") {
        e.preventDefault();
        // Nah shortcut: advance to next
        setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1));
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        // Flag shortcut: advance to next
        setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1));
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [photoGroups.length]);

  // Determine best shots based on sharpness in clusters
  useEffect(() => {
    const loadedThumbnails = Object.values(thumbnails);
    if (loadedThumbnails.length === 0) return;

    const bestSet = new Set<string>();
    for (const group of photoGroups) {
      const t = thumbnails[group.representative];
      if (t && t.sharpness > 75.0) {
        bestSet.add(group.stem);
      }
    }
    setBestShotStems(bestSet);
  }, [thumbnails, photoGroups]);

  return (
    <div className="flex flex-col h-screen w-screen bg-canvas text-zinc-100 overflow-hidden font-sans">
      {/* Unified Window Titlebar with macOS Traffic Light Spacing */}
      <header
        data-tauri-drag-region
        className="h-11 bg-panel/85 backdrop-blur-md border-b border-white/[0.08] flex items-center justify-between px-4 select-none shrink-0 z-30"
      >
        {/* Left: macOS traffic lights offset & Title */}
        <div className="flex items-center gap-3 pl-16">
          <span className="font-display font-semibold text-xs tracking-wide text-zinc-200">
            Keep or Nah
          </span>
          {selectedFolder && (
            <>
              <span className="text-zinc-500 text-xs">/</span>
              <span className="text-xs text-zinc-400 font-mono truncate max-w-sm">
                {selectedFolder}
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] bg-zinc-800 text-zinc-400 font-mono">
                {photoGroups.length} {photoGroups.length === 1 ? "group" : "groups"}
              </span>
            </>
          )}
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleOpenFolder}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition-all duration-150 border border-white/[0.06] active:scale-95 cursor-pointer"
          >
            <FolderOpen className="w-3.5 h-3.5 text-zinc-400" />
            <span>{isLoading ? "Scanning..." : "Open Folder"}</span>
          </button>
        </div>
      </header>

      {/* Main Studio Canvas Viewport */}
      <main className="flex-1 relative bg-canvas overflow-hidden flex items-center justify-center">
        {photoGroups.length > 0 && activeGroup ? (
          <>
            <PreviewViewport
              filePath={activeGroup.representative}
              stem={activeGroup.stem}
              exif={exifCache[activeGroup.representative] ?? null}
            />

            {/* Floating Glass Action HUD */}
            <ActionHud
              onKeep={() => setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1))}
              onNah={() => setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1))}
              onFlag={() => setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1))}
            />
          </>
        ) : selectedFolder ? (
          <div className="flex flex-col items-center justify-center gap-3 p-8 rounded-xl bg-panel/60 border border-white/[0.08] shadow-2xl max-w-md text-center">
            <h2 className="text-sm font-semibold text-zinc-200">No Supported Photos Found</h2>
            <p className="text-xs text-zinc-400 font-mono break-all bg-zinc-950/60 p-2.5 rounded border border-white/[0.04]">
              {selectedFolder}
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center gap-4 text-center max-w-sm">
            <div className="w-16 h-16 rounded-2xl bg-panel border border-white/[0.08] shadow-xl flex items-center justify-center text-zinc-400">
              <Sparkles className="w-7 h-7 text-accent" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-zinc-200 tracking-tight">
                No Photo Session Loaded
              </h1>
              <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                Open a folder of photos to rapidly review, compare, and organize your shoots.
              </p>
            </div>
            <button
              onClick={handleOpenFolder}
              className="mt-2 flex items-center gap-2 px-4 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-semibold shadow-lg shadow-accent/20 transition-all duration-150 active:scale-95 cursor-pointer"
            >
              <FolderOpen className="w-4 h-4" />
              <span>Choose Photo Folder</span>
            </button>
          </div>
        )}
      </main>

      {/* Virtualized Horizontal Thumbnail Strip */}
      <PhotoStrip
        groups={photoGroups}
        activeIndex={activeIndex}
        thumbnails={thumbnails}
        onSelect={(idx) => setActiveIndex(idx)}
        bestShotStems={bestShotStems}
      />

      {/* Studio Footer Status */}
      <footer className="h-7 bg-panel border-t border-white/[0.06] flex items-center justify-between px-3 text-[11px] text-zinc-500 select-none shrink-0 font-mono">
        <div className="flex items-center gap-3">
          <span>Tauri v2 · Native Desktop</span>
          {photoGroups.length > 0 && (
            <span>Shortcuts: 1 Keep · 2 Nah · F Flag · ⌘+Wheel Zoom · 0 Fit</span>
          )}
        </div>
        <span>
          {photoGroups.length > 0 ? `Photo ${activeIndex + 1} of ${photoGroups.length}` : "Ready"}
        </span>
      </footer>
    </div>
  );
}
