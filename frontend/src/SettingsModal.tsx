import React, { useEffect } from "react";
import { ViewMode } from "./PreviewViewport";
import { Settings, ArrowUp, ArrowDown, RotateCcw, X, Square, Columns2 } from "lucide-react";

export interface AppSettings {
  defaultViewMode: ViewMode;
  formatPriority: string[];
}

export const DEFAULT_FORMAT_PRIORITY = [
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".arw",
  ".cr2",
  ".cr3",
  ".nef",
  ".dng",
  ".tiff",
  ".bmp",
];

export const DEFAULT_SETTINGS: AppSettings = {
  defaultViewMode: "1-up",
  formatPriority: DEFAULT_FORMAT_PRIORITY,
};

const SETTINGS_STORAGE_KEY = "keep_or_nah_user_settings";

export function loadStoredSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        defaultViewMode:
          parsed.defaultViewMode === "2-up" ? "2-up" : "1-up",
        formatPriority:
          Array.isArray(parsed.formatPriority) && parsed.formatPriority.length > 0
            ? parsed.formatPriority
            : DEFAULT_FORMAT_PRIORITY,
      };
    }
  } catch (e) {
    console.error("Failed to load settings from storage:", e);
  }
  return DEFAULT_SETTINGS;
}

export function saveStoredSettings(settings: AppSettings): void {
  try {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch (e) {
    console.error("Failed to save settings to storage:", e);
  }
}

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  settings: AppSettings;
  onUpdateSettings: (newSettings: AppSettings) => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  settings,
  onUpdateSettings,
}) => {
  // ESC to close modal
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleMoveUp = (index: number) => {
    if (index <= 0) return;
    const updated = [...settings.formatPriority];
    const temp = updated[index - 1];
    updated[index - 1] = updated[index];
    updated[index] = temp;
    const next = { ...settings, formatPriority: updated };
    saveStoredSettings(next);
    onUpdateSettings(next);
  };

  const handleMoveDown = (index: number) => {
    if (index >= settings.formatPriority.length - 1) return;
    const updated = [...settings.formatPriority];
    const temp = updated[index + 1];
    updated[index + 1] = updated[index];
    updated[index] = temp;
    const next = { ...settings, formatPriority: updated };
    saveStoredSettings(next);
    onUpdateSettings(next);
  };

  const handleResetDefaults = () => {
    saveStoredSettings(DEFAULT_SETTINGS);
    onUpdateSettings(DEFAULT_SETTINGS);
  };

  const handleSelectDefaultViewMode = (mode: ViewMode) => {
    const next = { ...settings, defaultViewMode: mode };
    saveStoredSettings(next);
    onUpdateSettings(next);
  };

  return (
    <div
      data-testid="settings-modal"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-in fade-in duration-150 select-none font-sans"
    >
      <div className="relative w-full max-w-lg rounded-2xl bg-panel border border-white/[0.12] shadow-2xl flex flex-col overflow-hidden text-zinc-100 max-h-[85vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-white/[0.08] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-zinc-800/80 border border-white/[0.06] text-accent">
              <Settings className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold tracking-tight text-zinc-100">
                Preferences
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5">
                Configure format priority and default session view.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            data-testid="settings-close-btn"
            title="Close (Esc)"
            className="p-1.5 rounded-lg hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="px-6 py-5 overflow-y-auto space-y-6 text-xs">
          {/* Default View Mode Setting */}
          <div className="space-y-2.5">
            <label className="text-xs font-semibold text-zinc-300 block">
              Default View Mode on Launch
            </label>
            <div className="grid grid-cols-2 gap-2.5">
              <button
                type="button"
                data-testid="setting-mode-1up"
                onClick={() => handleSelectDefaultViewMode("1-up")}
                className={`flex items-center gap-2.5 p-3 rounded-xl border text-left transition cursor-pointer ${
                  settings.defaultViewMode === "1-up"
                    ? "bg-accent/15 border-accent text-zinc-100 shadow-sm"
                    : "bg-zinc-900/60 border-white/[0.06] text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900"
                }`}
              >
                <Square className="w-4 h-4 shrink-0 text-accent" />
                <div>
                  <div className="font-semibold text-xs text-zinc-200">1-Up Single</div>
                  <div className="text-[11px] text-zinc-400">Standard single photo preview</div>
                </div>
              </button>

              <button
                type="button"
                data-testid="setting-mode-2up"
                onClick={() => handleSelectDefaultViewMode("2-up")}
                className={`flex items-center gap-2.5 p-3 rounded-xl border text-left transition cursor-pointer ${
                  settings.defaultViewMode === "2-up"
                    ? "bg-accent/15 border-accent text-zinc-100 shadow-sm"
                    : "bg-zinc-900/60 border-white/[0.06] text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900"
                }`}
              >
                <Columns2 className="w-4 h-4 shrink-0 text-amber-400" />
                <div>
                  <div className="font-semibold text-xs text-zinc-200">2-Up Comparison</div>
                  <div className="text-[11px] text-zinc-400">Side-by-side comparison</div>
                </div>
              </button>
            </div>
          </div>

          {/* Format Priority Ordering */}
          <div className="space-y-2.5">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-xs font-semibold text-zinc-300 block">
                  Representative Format Priority
                </label>
                <p className="text-[11px] text-zinc-400 mt-0.5">
                  Formats higher in the list are chosen first when a group has multiple files.
                </p>
              </div>
              <button
                type="button"
                data-testid="settings-reset-btn"
                onClick={handleResetDefaults}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-zinc-400 hover:text-zinc-200 bg-zinc-800/60 hover:bg-zinc-800 border border-white/[0.06] transition cursor-pointer"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Reset</span>
              </button>
            </div>

            <div className="rounded-xl border border-white/[0.08] bg-zinc-950/60 divide-y divide-white/[0.04] overflow-hidden">
              {settings.formatPriority.map((ext, idx) => (
                <div
                  key={ext}
                  data-testid={`format-priority-item-${ext.replace(".", "")}`}
                  className="px-3.5 py-2 flex items-center justify-between hover:bg-zinc-900/40 transition"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="w-4 text-center font-mono text-[10px] text-zinc-500">
                      {idx + 1}
                    </span>
                    <span className="font-mono text-xs font-semibold text-zinc-200 uppercase">
                      {ext.replace(".", "")}
                    </span>
                    <span className="text-[10px] text-zinc-500">({ext})</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={idx === 0}
                      onClick={() => handleMoveUp(idx)}
                      data-testid={`priority-up-${ext.replace(".", "")}`}
                      title="Move up"
                      className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-20 disabled:pointer-events-none transition cursor-pointer"
                    >
                      <ArrowUp className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      disabled={idx === settings.formatPriority.length - 1}
                      onClick={() => handleMoveDown(idx)}
                      data-testid={`priority-down-${ext.replace(".", "")}`}
                      title="Move down"
                      className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-20 disabled:pointer-events-none transition cursor-pointer"
                    >
                      <ArrowDown className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 bg-zinc-950/40 border-t border-white/[0.08] flex items-center justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition border border-white/[0.06] cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
