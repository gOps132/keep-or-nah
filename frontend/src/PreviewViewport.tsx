import React, { useState, useRef, useEffect, useCallback } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { ExifMetadataDto } from "./types";
import { ZoomIn, ZoomOut, Maximize2, Camera } from "lucide-react";

interface PreviewViewportProps {
  filePath: string;
  stem: string;
  exif: ExifMetadataDto | null;
}

export const PreviewViewport: React.FC<PreviewViewportProps> = ({
  filePath,
  stem,
  exif,
}) => {
  const [zoom, setZoom] = useState<number>(1.0);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const dragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  const resetView = useCallback(() => {
    setZoom(1.0);
    setPan({ x: 0, y: 0 });
  }, []);

  // Reset zoom on photo change
  useEffect(() => {
    resetView();
  }, [filePath, resetView]);

  // Handle wheel zoom and keyboard shortcut '0'
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
      // Pan with two-finger trackpad swipe when zoomed
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

  const imageSrc = convertFileSrc(filePath);

  return (
    <div
      ref={containerRef}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      className="relative w-full h-full flex items-center justify-center overflow-hidden bg-canvas select-none cursor-grab active:cursor-grabbing"
    >
      {/* Zoom HUD Controls */}
      <div className="absolute top-4 right-4 z-20 flex items-center gap-1.5 p-1 rounded-lg bg-zinc-950/70 backdrop-blur-md border border-white/[0.08] shadow-lg">
        <button
          onClick={() => setZoom((prev) => Math.max(prev / 1.25, 0.25))}
          title="Zoom Out (⌘ -)"
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
        <span className="px-2 text-xs font-mono text-zinc-300 min-w-12 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom((prev) => Math.min(prev * 1.25, 6.0))}
          title="Zoom In (⌘ +)"
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          onClick={resetView}
          title="Fit to Window (0)"
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* EXIF Metadata Telemetry Pill */}
      {exif && (exif.shutter_speed || exif.aperture || exif.iso || exif.camera_model) && (
        <div className="absolute top-4 left-4 z-20 flex items-center gap-2.5 px-3 py-1.5 rounded-lg bg-zinc-950/70 backdrop-blur-md border border-white/[0.08] shadow-lg text-[11px] font-mono text-zinc-300">
          <Camera className="w-3.5 h-3.5 text-accent" />
          {exif.camera_model && <span className="text-zinc-200 font-semibold">{exif.camera_model}</span>}
          {exif.shutter_speed && <span>{exif.shutter_speed}</span>}
          {exif.aperture && <span className="text-blue-400">{exif.aperture}</span>}
          {exif.iso && <span className="text-amber-400">{exif.iso}</span>}
          {exif.focal_length && <span>{exif.focal_length}</span>}
        </div>
      )}

      {/* Main Image Viewport with 60fps transform */}
      <div
        style={{
          transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
          transition: isDragging ? "none" : "transform 0.08s ease-out",
        }}
        className="w-full h-full flex items-center justify-center p-8 pointer-events-none will-change-transform"
      >
        <img
          src={imageSrc}
          alt={stem}
          className="max-w-full max-h-full object-contain rounded shadow-2xl"
          draggable={false}
        />
      </div>
    </div>
  );
};
