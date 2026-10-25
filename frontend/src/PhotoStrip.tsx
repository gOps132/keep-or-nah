import React, { useEffect, useRef } from "react";
import { PhotoGroup, ThumbnailData } from "./types";
import { Image as ImageIcon, Star } from "lucide-react";

interface PhotoStripProps {
  groups: PhotoGroup[];
  activeIndex: number;
  thumbnails: Record<string, ThumbnailData>;
  onSelect: (index: number) => void;
  bestShotStems?: Set<string>;
}

export const PhotoStrip: React.FC<PhotoStripProps> = ({
  groups,
  activeIndex,
  thumbnails,
  onSelect,
  bestShotStems = new Set(),
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeItemRef = useRef<HTMLButtonElement>(null);

  // Auto-scroll active item into view smoothly
  useEffect(() => {
    if (activeItemRef.current && typeof activeItemRef.current.scrollIntoView === "function") {
      activeItemRef.current.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "center",
      });
    }
  }, [activeIndex]);

  if (groups.length === 0) {
    return null;
  }

  return (
    <div
      ref={containerRef}
      className="h-28 bg-[#121214] border-t border-white/[0.08] px-4 py-3 flex items-center gap-3 overflow-x-auto scrollbar-thin scrollbar-thumb-zinc-700 select-none shrink-0"
    >
      {groups.map((group, idx) => {
        const isActive = idx === activeIndex;
        const thumb = thumbnails[group.representative];
        const isBestShot = bestShotStems.has(group.stem);

        return (
          <button
            key={group.stem}
            ref={isActive ? activeItemRef : null}
            onClick={() => onSelect(idx)}
            className={`group relative flex flex-col items-center justify-between w-24 h-20 rounded-md p-1.5 transition-all duration-150 shrink-0 text-left cursor-pointer border ${
              isActive
                ? "bg-zinc-800/90 border-accent ring-2 ring-accent/60 shadow-lg shadow-black/40"
                : "bg-zinc-900/60 border-white/[0.06] hover:bg-zinc-800/60 hover:border-white/[0.12]"
            }`}
          >
            {/* Best Shot Badge */}
            {isBestShot && (
              <span
                title="Best Shot in Burst (High Sharpness)"
                className="absolute top-1 right-1 z-10 w-4 h-4 rounded-full bg-amber-500/90 text-zinc-950 flex items-center justify-center shadow"
              >
                <Star className="w-2.5 h-2.5 fill-current" />
              </span>
            )}

            {/* Thumbnail Canvas / Placeholder */}
            <div className="w-full flex-1 rounded bg-zinc-950/80 overflow-hidden flex items-center justify-center relative">
              {thumb ? (
                <img
                  src={thumb.data_url}
                  alt={group.stem}
                  className="w-full h-full object-contain"
                  loading="lazy"
                />
              ) : (
                <ImageIcon className="w-5 h-5 text-zinc-600 animate-pulse" />
              )}
            </div>

            {/* Stem Label */}
            <div className="w-full mt-1 flex items-center justify-between text-[10px] font-mono leading-none">
              <span className="truncate text-zinc-400 group-hover:text-zinc-200">
                {group.stem}
              </span>
              <span className="text-zinc-600 text-[9px] shrink-0 ml-1">
                {idx + 1}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
};
