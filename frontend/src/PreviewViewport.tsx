import React, { useState, useRef, useEffect, useCallback } from "react";
import { convertFileSrc, isTauri } from "@tauri-apps/api/core";
import { ExifMetadataDto } from "./types";
import { ZoomIn, ZoomOut, Maximize2, Camera, Star } from "lucide-react";

export type ViewMode = "1-up" | "2-up";

export interface PhotoViewItem {
  filePath: string;
  sourcePath?: string;
  stem: string;
  exif: ExifMetadataDto | null;
  isBestShot?: boolean;
  burstTag?: string;
  members?: string[];
  selectedMember?: string;
  onSelectMember?: (memberPath: string) => void;
  rawStatus?: "fast" | "full" | "loading" | null;
}

const VIEWABLE_EXTENSIONS = new Set([
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".bmp",
  ".gif",
  ".tiff",
  ".tif",
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
]);

const RAW_EXTENSIONS = new Set([
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
]);

export const isRawFile = (path: string): boolean => {
  const dotIndex = path.lastIndexOf(".");
  if (dotIndex < 0) return false;
  return RAW_EXTENSIONS.has(path.slice(dotIndex).toLowerCase());
};

export const isViewableFormat = (path: string): boolean => {
  const dotIndex = path.lastIndexOf(".");
  if (dotIndex < 0) return false;
  return VIEWABLE_EXTENSIONS.has(path.slice(dotIndex).toLowerCase());
};

export const getFormatLabel = (path: string): string => {
  const dotIndex = path.lastIndexOf(".");
  if (dotIndex < 0) return "FILE";
  const ext = path.slice(dotIndex + 1).toUpperCase();
  return ext || "FILE";
};

export const FormatPills: React.FC<{
  members?: string[];
  selectedMember?: string;
  onSelectMember?: (path: string) => void;
  rawStatus?: "fast" | "full" | "loading" | null;
}> = ({ members, selectedMember, onSelectMember, rawStatus }) => {
  if (!members || members.length <= 1) return null;

  const isSelectedRaw = selectedMember && isRawFile(selectedMember);

  return (
    <div
      data-testid="format-pills"
      className="flex items-center gap-1 p-1 rounded-lg bg-zinc-950/80 backdrop-blur-md border border-white/[0.08] shadow-lg text-[11px] font-mono z-20"
    >
      <span className="text-[9px] text-zinc-500 font-bold px-1 select-none">FORMATS</span>
      {members.map((member) => {
        const label = getFormatLabel(member);
        const viewable = isViewableFormat(member);
        const isSelected = selectedMember ? selectedMember === member : false;

        if (!viewable) {
          return (
            <span
              key={member}
              data-testid={`format-pill-${label.toLowerCase()}`}
              title={`${label} sidecar (non-viewable)`}
              className="px-1.5 py-0.5 rounded text-[9px] font-semibold text-zinc-500 bg-zinc-900/60 border border-white/[0.04] cursor-default select-none"
            >
              {label}
            </span>
          );
        }

        return (
          <button
            key={member}
            type="button"
            data-testid={`format-pill-${label.toLowerCase()}`}
            title={`View ${label} format (or press V)`}
            onClick={() => onSelectMember?.(member)}
            className={`px-2 py-0.5 rounded font-semibold text-[10px] transition cursor-pointer select-none ${
              isSelected
                ? "bg-accent text-white shadow-sm ring-1 ring-accent/50"
                : "bg-zinc-800/80 hover:bg-zinc-700 text-zinc-300"
            }`}
          >
            {label}
          </button>
        );
      })}

      {isSelectedRaw && rawStatus && (
        <span
          data-testid="raw-status-badge"
          className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ml-1 select-none flex items-center gap-1 border ${
            rawStatus === "full"
              ? "text-emerald-400 bg-emerald-950/80 border-emerald-500/30"
              : "text-amber-400 bg-amber-950/80 border-amber-500/30"
          }`}
          title={
            rawStatus === "full"
              ? "True 14-bit hardware-accelerated RAW demosaic active"
              : "Fast embedded preview active while RAW demosaicing in background"
          }
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              rawStatus === "full" ? "bg-emerald-400" : "bg-amber-400 animate-pulse"
            }`}
          />
          {rawStatus === "full" ? "RAW (Full)" : "RAW (Fast)"}
        </span>
      )}
    </div>
  );
};

interface PreviewViewportProps {
  filePath?: string;
  stem?: string;
  exif?: ExifMetadataDto | null;
  viewMode?: ViewMode;
  primary?: PhotoViewItem;
  comparison?: PhotoViewItem | null;
  compareTarget?: "photo" | "format";
  onToggleCompareTarget?: (target: "photo" | "format") => void;
  hasMultipleFormats?: boolean;
}

export const PreviewViewport: React.FC<PreviewViewportProps> = ({
  filePath,
  stem,
  exif,
  viewMode = "1-up",
  primary,
  comparison,
  compareTarget = "photo",
  onToggleCompareTarget,
  hasMultipleFormats = false,
}) => {
  const activePrimary: PhotoViewItem = primary || {
    filePath: filePath || "",
    stem: stem || "",
    exif: exif || null,
  };

  const [zoom, setZoom] = useState<number>(1.0);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const dragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  const resetView = useCallback(() => {
    setZoom(1.0);
    setPan({ x: 0, y: 0 });
  }, []);

  // Reset zoom only on photo change (tracked by sourcePath or stem), NOT on hot-swap of render path!
  useEffect(() => {
    resetView();
  }, [
    activePrimary.sourcePath || activePrimary.stem,
    comparison?.sourcePath || comparison?.stem,
    resetView,
  ]);

  // Handle keyboard shortcut '0' for reset view
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "0") {
        e.preventDefault();
        resetView();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [resetView]);

  const handleWheel = (e: React.WheelEvent) => {
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 1.15 : 0.85;
      setZoom((prev) => Math.min(Math.max(prev * delta, 0.25), 6.0));
    } else if (zoom > 1.0) {
      setPan((prev) => ({
        x: prev.x - e.deltaX,
        y: prev.y - e.deltaY,
      }));
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (zoom > 1.0 || e.button === 0) {
      setIsDragging(true);
      dragStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging) {
      setPan({
        x: e.clientX - dragStartRef.current.x,
        y: e.clientY - dragStartRef.current.y,
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const toSrc = (path: string) => {
    if (!path) return "";
    return isTauri() ? convertFileSrc(path) : path;
  };

  const isSplit = viewMode === "2-up" && comparison != null;

  return (
    <div
      ref={containerRef}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      data-testid="preview-viewport-container"
      className="relative w-full h-full flex items-center justify-center overflow-hidden bg-canvas select-none cursor-grab active:cursor-grabbing"
    >
      {/* Zoom HUD Controls */}
      <div className="absolute top-4 right-4 z-20 flex items-center gap-1.5 p-1 rounded-lg bg-zinc-950/70 backdrop-blur-md border border-white/[0.08] shadow-lg">
        <button
          onClick={() => setZoom((prev) => Math.max(prev / 1.25, 0.25))}
          title="Zoom Out (⌘ -)"
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
        <span className="px-2 text-xs font-mono text-zinc-300 min-w-12 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom((prev) => Math.min(prev * 1.25, 6.0))}
          title="Zoom In (⌘ +)"
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          onClick={resetView}
          title="Fit to Window (0)"
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Viewport Content */}
      {isSplit ? (
        <div className="w-full h-full grid grid-cols-2 divide-x divide-white/[0.08]">
          {/* Left Split Pane: Active Photo */}
          <div className="relative w-full h-full overflow-hidden flex items-center justify-center">
            <div className="absolute top-4 left-4 z-20 flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-950/80 backdrop-blur-md border border-white/[0.08] shadow-lg text-[11px] font-mono text-zinc-300">
                <span className="px-1.5 py-0.5 rounded bg-accent/20 text-accent font-semibold text-[10px]">
                  Active
                </span>
                <span className="font-semibold text-zinc-200">{activePrimary.stem}</span>
                {activePrimary.burstTag && (
                  <span className="px-1 py-0.2 rounded bg-indigo-600/80 text-white text-[9px] font-bold">
                    {activePrimary.burstTag}
                  </span>
                )}
                {activePrimary.isBestShot && (
                  <span className="text-amber-400 flex items-center gap-0.5 text-[10px] font-semibold">
                    <Star className="w-3 h-3 fill-current" />
                    Best Shot
                  </span>
                )}
                {activePrimary.exif && activePrimary.exif.camera_model && (
                  <span className="text-zinc-400 border-l border-white/10 pl-2">
                    {activePrimary.exif.camera_model}
                  </span>
                )}
              </div>
              <FormatPills
                members={activePrimary.members}
                selectedMember={activePrimary.selectedMember}
                onSelectMember={activePrimary.onSelectMember}
                rawStatus={activePrimary.rawStatus}
              />
            </div>

            <div
              data-testid="split-left-pane"
              style={{
                transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
                transition: isDragging ? "none" : "transform 0.08s ease-out",
              }}
              className="w-full h-full flex items-center justify-center p-6 pointer-events-none will-change-transform"
            >
              <img
                src={toSrc(activePrimary.filePath)}
                alt={activePrimary.stem}
                className="max-w-full max-h-full object-contain rounded shadow-2xl"
                draggable={false}
              />
            </div>
          </div>

          {/* Right Split Pane: Comparison Target Photo */}
          <div className="relative w-full h-full overflow-hidden flex items-center justify-center">
            <div className="absolute top-4 left-4 z-20 flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-950/80 backdrop-blur-md border border-white/[0.08] shadow-lg text-[11px] font-mono text-zinc-300">
                <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-semibold text-[10px]">
                  {compareTarget === "format"
                    ? "Format Compare"
                    : comparison.isBestShot
                    ? "★ Best Shot"
                    : "Compare"}
                </span>
                <span className="font-semibold text-zinc-200">{comparison.stem}</span>
                {comparison.burstTag && (
                  <span className="px-1 py-0.2 rounded bg-indigo-600/80 text-white text-[9px] font-bold">
                    {comparison.burstTag}
                  </span>
                )}
                {comparison.exif && comparison.exif.camera_model && (
                  <span className="text-zinc-400 border-l border-white/10 pl-2">
                    {comparison.exif.camera_model}
                  </span>
                )}
              </div>
              {hasMultipleFormats && (
                <div
                  data-testid="compare-target-toggle"
                  className="flex items-center gap-1 p-0.5 rounded-lg bg-zinc-950/80 backdrop-blur-md border border-white/[0.08] text-[10px] font-mono z-20"
                >
                  <button
                    type="button"
                    data-testid="compare-adjacent-btn"
                    onClick={() => onToggleCompareTarget?.("photo")}
                    className={`px-2 py-0.5 rounded font-semibold transition cursor-pointer select-none ${
                      compareTarget === "photo"
                        ? "bg-accent text-white"
                        : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    Adjacent
                  </button>
                  <button
                    type="button"
                    data-testid="compare-format-btn"
                    title="Compare Formats (X)"
                    onClick={() => onToggleCompareTarget?.("format")}
                    className={`px-2 py-0.5 rounded font-semibold transition cursor-pointer select-none ${
                      compareTarget === "format"
                        ? "bg-accent text-white"
                        : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    Formats (X)
                  </button>
                </div>
              )}
              <FormatPills
                members={comparison.members}
                selectedMember={comparison.selectedMember}
                onSelectMember={comparison.onSelectMember}
                rawStatus={comparison.rawStatus}
              />
            </div>

            <div
              data-testid="split-right-pane"
              style={{
                transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
                transition: isDragging ? "none" : "transform 0.08s ease-out",
              }}
              className="w-full h-full flex items-center justify-center p-6 pointer-events-none will-change-transform"
            >
              <img
                src={toSrc(comparison.filePath)}
                alt={comparison.stem}
                className="max-w-full max-h-full object-contain rounded shadow-2xl"
                draggable={false}
              />
            </div>
          </div>
        </div>
      ) : (
        /* Standard 1-Up Single Pane Viewport */
        <>
          <div className="absolute top-4 left-4 z-20 flex flex-wrap items-center gap-2">
            {activePrimary.exif &&
              (activePrimary.exif.shutter_speed ||
                activePrimary.exif.aperture ||
                activePrimary.exif.iso ||
                activePrimary.exif.camera_model) && (
                <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg bg-zinc-950/70 backdrop-blur-md border border-white/[0.08] shadow-lg text-[11px] font-mono text-zinc-300">
                  <Camera className="w-3.5 h-3.5 text-accent" />
                  {activePrimary.exif.camera_model && (
                    <span className="text-zinc-200 font-semibold">
                      {activePrimary.exif.camera_model}
                    </span>
                  )}
                  {activePrimary.exif.shutter_speed && (
                    <span>{activePrimary.exif.shutter_speed}</span>
                  )}
                  {activePrimary.exif.aperture && (
                    <span className="text-blue-400">{activePrimary.exif.aperture}</span>
                  )}
                  {activePrimary.exif.iso && (
                    <span className="text-amber-400">{activePrimary.exif.iso}</span>
                  )}
                  {activePrimary.exif.focal_length && (
                    <span>{activePrimary.exif.focal_length}</span>
                  )}
                </div>
              )}
            <FormatPills
              members={activePrimary.members}
              selectedMember={activePrimary.selectedMember}
              onSelectMember={activePrimary.onSelectMember}
              rawStatus={activePrimary.rawStatus}
            />
          </div>

          <div
            data-testid="single-pane"
            style={{
              transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
              transition: isDragging ? "none" : "transform 0.08s ease-out",
            }}
            className="w-full h-full flex items-center justify-center p-8 pointer-events-none will-change-transform"
          >
            <img
              src={toSrc(activePrimary.filePath)}
              alt={activePrimary.stem}
              className="max-w-full max-h-full object-contain rounded shadow-2xl"
              draggable={false}
            />
          </div>
        </>
      )}
    </div>
  );
};
