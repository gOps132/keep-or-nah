import React, { useState } from "react";
import { BatchSummaryDto } from "./types";
import { CheckCircle2, Trash2, ArrowRight, Loader2, X } from "lucide-react";

interface ReviewCommitModalProps {
  isOpen: boolean;
  onClose: () => void;
  summary: BatchSummaryDto;
  onConfirmCommit: (actionMode: "move" | "copy") => Promise<void>;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export const ReviewCommitModal: React.FC<ReviewCommitModalProps> = ({
  isOpen,
  onClose,
  summary,
  onConfirmCommit,
}) => {
  const [actionMode, setActionMode] = useState<"move" | "copy">("move");
  const [isCommitting, setIsCommitting] = useState<boolean>(false);

  if (!isOpen) return null;

  const handleCommit = async () => {
    try {
      setIsCommitting(true);
      await onConfirmCommit(actionMode);
      onClose();
    } catch (err) {
      console.error("Failed to commit batch:", err);
    } finally {
      setIsCommitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-in fade-in duration-150 select-none font-sans">
      <div className="relative w-full max-w-xl rounded-2xl bg-panel border border-white/[0.12] shadow-2xl flex flex-col overflow-hidden text-zinc-100">
        {/* Header */}
        <div className="px-6 py-4 border-b border-white/[0.08] flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold tracking-tight text-zinc-100">
              Review Staged Decisions
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Confirm before executing atomic file operations.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Summary Stats Row */}
        <div className="px-6 py-4 grid grid-cols-3 gap-3 bg-zinc-950/40 border-b border-white/[0.06]">
          <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.04] flex flex-col">
            <span className="text-[11px] text-zinc-400">Keep Groups</span>
            <div className="flex items-center gap-1.5 mt-1 text-emerald-400 font-semibold text-lg font-mono">
              <CheckCircle2 className="w-4 h-4" />
              <span>{summary.keep_count}</span>
            </div>
          </div>

          <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.04] flex flex-col">
            <span className="text-[11px] text-zinc-400">Nah / Discard</span>
            <div className="flex items-center gap-1.5 mt-1 text-red-400 font-semibold text-lg font-mono">
              <Trash2 className="w-4 h-4" />
              <span>{summary.nah_count}</span>
            </div>
          </div>

          <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.04] flex flex-col">
            <span className="text-[11px] text-zinc-400">Disk Reclaimed</span>
            <span className="mt-1 text-zinc-200 font-semibold text-lg font-mono">
              {formatBytes(summary.total_reclaimed_bytes)}
            </span>
          </div>
        </div>

        {/* Action Mode Segmented Switch */}
        <div className="px-6 py-3 border-b border-white/[0.06] flex items-center justify-between text-xs">
          <span className="text-zinc-400 font-medium">Transfer Action:</span>
          <div className="flex items-center p-0.5 rounded-lg bg-zinc-950 border border-white/[0.08]">
            <button
              onClick={() => setActionMode("move")}
              className={`px-3 py-1 rounded-md text-xs font-medium transition cursor-pointer ${
                actionMode === "move"
                  ? "bg-zinc-800 text-zinc-100 shadow"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Move from Source
            </button>
            <button
              onClick={() => setActionMode("copy")}
              className={`px-3 py-1 rounded-md text-xs font-medium transition cursor-pointer ${
                actionMode === "copy"
                  ? "bg-zinc-800 text-zinc-100 shadow"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Copy
            </button>
          </div>
        </div>

        {/* Staged Items Breakdown List */}
        <div className="max-h-60 overflow-y-auto p-4 space-y-1.5 font-mono text-xs scrollbar-thin scrollbar-thumb-zinc-700">
          {summary.items.map((item) => (
            <div
              key={item.stem}
              className="flex items-center justify-between px-3 py-2 rounded-lg bg-zinc-900/40 border border-white/[0.04]"
            >
              <div className="flex items-center gap-2">
                {item.decision === "keep" && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] bg-emerald-950/60 text-emerald-400 font-bold border border-emerald-800/40">
                    KEEP
                  </span>
                )}
                {item.decision === "nah" && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] bg-red-950/60 text-red-400 font-bold border border-red-800/40">
                    NAH
                  </span>
                )}
                {item.decision === "flag" && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-950/60 text-amber-400 font-bold border border-amber-800/40">
                    FLAG
                  </span>
                )}
                <span className="text-zinc-200">{item.stem}</span>
              </div>
              <div className="flex items-center gap-2 text-zinc-500 text-[11px]">
                <span>{item.file_count} {item.file_count === 1 ? "file" : "files"}</span>
                <span>·</span>
                <span>{formatBytes(item.total_bytes)}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 border-t border-white/[0.08] flex items-center justify-between bg-zinc-950/30">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition cursor-pointer"
          >
            Cancel
          </button>

          <button
            onClick={handleCommit}
            disabled={isCommitting || summary.total_groups === 0}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-semibold shadow-lg shadow-accent/20 transition active:scale-95 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
          >
            {isCommitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Executing Batch...</span>
              </>
            ) : (
              <>
                <span>Commit {summary.total_groups} Staged Groups</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
