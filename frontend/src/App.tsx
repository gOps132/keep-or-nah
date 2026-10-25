import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { FolderOpen, Sparkles, Image as ImageIcon, ChevronLeft, ChevronRight } from "lucide-react";
import { PhotoGroup, ThumbnailData } from "./types";
import { PhotoStrip } from "./PhotoStrip";

export default function App() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [photoGroups, setPhotoGroups] = useState<PhotoGroup[]>([]);
  const [activeIndex, setActiveIndex] = useState<number>(0);
  const [thumbnails, setThumbnails] = useState<Record<string, ThumbnailData>>({});
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

  // Keyboard navigation: Arrow Left and Arrow Right
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (photoGroups.length === 0) return;

      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setActiveIndex((prev) => Math.max(0, prev - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
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

    // Identify items with exceptionally high sharpness scores (> 80.0)
    const bestSet = new Set<string>();
    for (const group of photoGroups) {
      const t = thumbnails[group.representative];
      if (t && t.sharpness > 75.0) {
        bestSet.add(group.stem);
      }
    }
    setBestShotStems(bestSet);
  }, [thumbnails, photoGroups]);

  const activeGroup = photoGroups[activeIndex] ?? null;
  const activeThumb = activeGroup ? thumbnails[activeGroup.representative] : null;

  return (
    <div className="flex flex-col h-screen w-screen bg-canvas text-zinc-100 overflow-hidden font-sans">
      {/* Unified Window Titlebar with macOS Traffic Light Spacing */}
      <header
        data-tauri-drag-region
        className="h-11 bg-panel/85 backdrop-blur-md border-b border-white/[0.08] flex items-center justify-between px-4 select-none shrink-0"
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
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition-all duration-150 border border-white/[0.06] active:scale-95"
          >
            <FolderOpen className="w-3.5 h-3.5 text-zinc-400" />
            <span>{isLoading ? "Scanning..." : "Open Folder"}</span>
          </button>
        </div>
      </header>

      {/* Main Studio Canvas Area */}
      <main className="flex-1 flex flex-col items-center justify-center p-6 relative bg-canvas overflow-hidden">
        {photoGroups.length > 0 && activeGroup ? (
          <div className="flex flex-col items-center justify-center h-full w-full max-w-4xl relative">
            {/* Quick Navigation Arrows */}
            <div className="absolute inset-y-0 left-0 flex items-center">
              <button
                onClick={() => setActiveIndex((prev) => Math.max(0, prev - 1))}
                disabled={activeIndex === 0}
                className="p-2 rounded-full bg-zinc-900/60 hover:bg-zinc-800 border border-white/[0.08] text-zinc-400 disabled:opacity-30 disabled:pointer-events-none transition cursor-pointer"
              >
                <ChevronLeft className="w-5 h-5" />
              </button>
            </div>
            <div className="absolute inset-y-0 right-0 flex items-center">
              <button
                onClick={() => setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1))}
                disabled={activeIndex === photoGroups.length - 1}
                className="p-2 rounded-full bg-zinc-900/60 hover:bg-zinc-800 border border-white/[0.08] text-zinc-400 disabled:opacity-30 disabled:pointer-events-none transition cursor-pointer"
              >
                <ChevronRight className="w-5 h-5" />
              </button>
            </div>

            {/* Photo Preview Card */}
            <div className="flex flex-col items-center justify-center gap-4 p-4 rounded-xl bg-panel/40 border border-white/[0.06] shadow-2xl">
              <div className="w-[480px] h-[340px] bg-zinc-950/80 rounded-lg overflow-hidden border border-white/[0.04] flex items-center justify-center relative">
                {activeThumb ? (
                  <img
                    src={activeThumb.data_url}
                    alt={activeGroup.stem}
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <ImageIcon className="w-12 h-12 text-zinc-700 animate-pulse" />
                )}
              </div>

              {/* Active Photo Info Bar */}
              <div className="flex items-center justify-between w-full px-2 text-xs font-mono">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-zinc-200">{activeGroup.stem}</span>
                  <span className="text-zinc-500 text-[11px]">
                    ({activeGroup.members.length} {activeGroup.members.length === 1 ? "file" : "files"})
                  </span>
                </div>
                <div className="flex items-center gap-2 text-zinc-400 text-[11px]">
                  <span>
                    Photo {activeIndex + 1} of {photoGroups.length}
                  </span>
                  {activeThumb && (
                    <span className="text-emerald-400">
                      Sharpness: {activeThumb.sharpness.toFixed(1)}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
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
            <span>Use ← / → arrow keys to navigate</span>
          )}
        </div>
        <span>
          {photoGroups.length > 0 ? `${photoGroups.length} Groups Loaded` : "Ready"}
        </span>
      </footer>
    </div>
  );
}
