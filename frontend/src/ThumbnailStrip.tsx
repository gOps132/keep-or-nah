import React, { useEffect, useRef } from "react";
import { PhotoGroup, ThumbnailData } from "./types";
import { Image as ImageIcon, Star, Check, X, Flag } from "lucide-react";

interface ThumbnailStripProps {
  groups: PhotoGroup[];
  activeIndex: number;
  thumbnails: Record<string, ThumbnailData>;
  stagedDecisions: Record<string, string>;
  onSelect: (index: number) => void;
  bestShotStems?: Set<string>;
}

export const ThumbnailStrip: React.FC<ThumbnailStripProps> = ({
  groups,
  activeIndex,
  thumbnails,
  stagedDecisions,
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
        const decision = stagedDecisions[group.stem];

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
            {/* Best Shot Badge (Top Right) */}
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

              {/* Staged Decision Badge (Floating Bottom Right of Image) */}
              {decision === "keep" && (
                <span className="absolute bottom-1 right-1 z-10 px-1 py-0.5 rounded bg-keep text-white text-[9px] font-bold shadow flex items-center gap-0.5">
                  <Check className="w-2.5 h-2.5 stroke-[3]" />
                </span>
              )}
              {decision === "nah" && (
                <span className="absolute bottom-1 right-1 z-10 px-1 py-0.5 rounded bg-nah text-white text-[9px] font-bold shadow flex items-center gap-0.5">
                  <X className="w-2.5 h-2.5 stroke-[3]" />
                </span>
              )}
              {decision === "flag" && (
                <span className="absolute bottom-1 right-1 z-10 px-1 py-0.5 rounded bg-flag text-white text-[9px] font-bold shadow flex items-center gap-0.5">
                  <Flag className="w-2.5 h-2.5 fill-current" />
                </span>
              )}
            </div>

            {/* Stem Label & Sequence */}
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
