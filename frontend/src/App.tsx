import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { FolderOpen, Sparkles } from "lucide-react";

export default function App() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleOpenFolder = async () => {
    try {
      setIsLoading(true);
      const folderPath = await invoke<string | null>("open_directory_dialog");
      if (folderPath) {
        setSelectedFolder(folderPath);
      }
    } catch (err) {
      console.error("Failed to open directory:", err);
    } finally {
      setIsLoading(false);
    }
  };

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
            <span>{isLoading ? "Opening..." : "Open Folder"}</span>
          </button>
        </div>
      </header>

      {/* Main Studio Canvas */}
      <main className="flex-1 flex flex-col items-center justify-center p-6 relative bg-canvas">
        {selectedFolder ? (
          <div className="flex flex-col items-center justify-center gap-3 p-8 rounded-xl bg-panel/60 border border-white/[0.08] shadow-2xl max-w-md text-center">
            <div className="w-12 h-12 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center text-accent">
              <FolderOpen className="w-6 h-6" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-200">Session Loaded</h2>
            <p className="text-xs text-zinc-400 font-mono break-all bg-zinc-950/60 p-2.5 rounded border border-white/[0.04]">
              {selectedFolder}
            </p>
            <p className="text-xs text-zinc-500">
              Ready for directory scan & thumbnail strip pipeline.
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

      {/* Subtle Studio Footer Bar */}
      <footer className="h-7 bg-panel border-t border-white/[0.06] flex items-center justify-between px-3 text-[11px] text-zinc-500 select-none shrink-0 font-mono">
        <span>Tauri v2 · Native Desktop</span>
        <span>Studio Dark Mode</span>
      </footer>
    </div>
  );
}
