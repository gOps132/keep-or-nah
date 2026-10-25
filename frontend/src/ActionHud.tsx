import React from "react";
import { Check, X, Flag } from "lucide-react";

interface ActionHudProps {
  onKeep: () => void;
  onNah: () => void;
  onFlag: () => void;
  disabled?: boolean;
}

export const ActionHud: React.FC<ActionHudProps> = ({
  onKeep,
  onNah,
  onFlag,
  disabled = false,
}) => {
  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 p-1.5 rounded-full bg-zinc-950/75 backdrop-blur-xl border border-white/[0.12] shadow-2xl shadow-black/60 select-none">
      <button
        onClick={onKeep}
        disabled={disabled}
        title="Keep this photo group (Key: 1)"
        className="flex items-center gap-2 px-4 py-2 rounded-full bg-keep hover:bg-emerald-600 active:scale-95 text-white text-xs font-semibold shadow-md transition-all duration-150 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
      >
        <Check className="w-4 h-4 stroke-[2.5]" />
        <span>Keep</span>
        <kbd className="px-1.5 py-0.5 rounded bg-black/25 text-emerald-200 text-[10px] font-mono leading-none">
          1
        </kbd>
      </button>

      <button
        onClick={onNah}
        disabled={disabled}
        title="Nah this photo group (Key: 2)"
        className="flex items-center gap-2 px-4 py-2 rounded-full bg-nah hover:bg-red-600 active:scale-95 text-white text-xs font-semibold shadow-md transition-all duration-150 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
      >
        <X className="w-4 h-4 stroke-[2.5]" />
        <span>Nah</span>
        <kbd className="px-1.5 py-0.5 rounded bg-black/25 text-red-200 text-[10px] font-mono leading-none">
          2
        </kbd>
      </button>

      <button
        onClick={onFlag}
        disabled={disabled}
        title="Flag for later re-examination (Key: F)"
        className="flex items-center gap-2 px-4 py-2 rounded-full bg-flag hover:bg-amber-600 active:scale-95 text-white text-xs font-semibold shadow-md transition-all duration-150 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
      >
        <Flag className="w-3.5 h-3.5 fill-current" />
        <span>Flag</span>
        <kbd className="px-1.5 py-0.5 rounded bg-black/25 text-amber-200 text-[10px] font-mono leading-none">
          F
        </kbd>
      </button>
    </div>
  );
};
