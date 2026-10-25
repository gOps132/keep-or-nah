import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { FolderOpen, Sparkles, Undo2, CheckSquare, Square, Columns2 } from "lucide-react";
import {
  PhotoGroup,
  ThumbnailData,
  ExifMetadataDto,
  BatchSummaryDto,
  CommitResultDto,
  BurstCluster,
  PhotoBurstInfo,
} from "./types";
import { ThumbnailStrip } from "./ThumbnailStrip";
import { PreviewViewport, ViewMode, isViewableFormat, isRawFile } from "./PreviewViewport";
import { ActionHud } from "./ActionHud";
import { ReviewCommitModal } from "./ReviewCommitModal";

export default function App() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [photoGroups, setPhotoGroups] = useState<PhotoGroup[]>([]);
  const [activeIndex, setActiveIndex] = useState<number>(0);
  const [thumbnails, setThumbnails] = useState<Record<string, ThumbnailData>>({});
  const [exifCache, setExifCache] = useState<Record<string, ExifMetadataDto>>({});
  const [stagedDecisions, setStagedDecisions] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [bestShotStems, setBestShotStems] = useState<Set<string>>(new Set());
  const [burstClusterMap, setBurstClusterMap] = useState<Record<string, string>>({});
  const [viewMode, setViewMode] = useState<ViewMode>("1-up");
  const [compareTarget, setCompareTarget] = useState<"photo" | "format">("photo");
  const [activeMemberOverride, setActiveMemberOverride] = useState<Record<string, string>>({});
  const [comparisonMemberOverride, setComparisonMemberOverride] = useState<Record<string, string>>({});
  const [resolvedPreviewMap, setResolvedPreviewMap] = useState<Record<string, string>>({});

  // Review modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [batchSummary, setBatchSummary] = useState<BatchSummaryDto>({
    total_groups: 0,
    keep_count: 0,
    nah_count: 0,
    flag_count: 0,
    total_files: 0,
    total_reclaimed_bytes: 0,
    items: [],
  });

  // Listen for asynchronously streamed progressive thumbnail events
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    listen<ThumbnailData>("thumbnail-ready", (event) => {
      const thumb = event.payload;
      setThumbnails((prev) => ({
        ...prev,
        [thumb.path]: thumb,
      }));
    })
      .then((fn) => {
        unlisten = fn;
      })
      .catch((err) => {
        console.warn("Event listener for thumbnail-ready unavailable:", err);
      });

    return () => {
      if (unlisten) unlisten();
    };
  }, []);

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
      setStagedDecisions({});

      // Asynchronously stream thumbnails over Tauri IPC events
      invoke("start_thumbnail_stream", {
        paths: groups.map((g) => g.representative),
        maxEdge: 160,
      }).catch((err) => {
        console.error("Failed to start thumbnail stream:", err);
      });
    } catch (err) {
      console.error("Failed to scan directory:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Compute burst clusters and relative Best Shot whenever thumbnails update
  useEffect(() => {
    const thumbEntries = Object.values(thumbnails);
    if (thumbEntries.length === 0) {
      setBurstClusterMap({});
      setBestShotStems(new Set());
      return;
    }

    const burstPhotos: PhotoBurstInfo[] = thumbEntries
      .filter((t) => typeof t.image_hash === "number" && typeof t.timestamp === "number")
      .map((t) => ({
        path: t.path,
        timestamp: t.timestamp!,
        image_hash: t.image_hash!,
        sharpness: t.sharpness,
      }));

    if (burstPhotos.length === 0) return;

    invoke<BurstCluster[]>("compute_burst_clusters", { photos: burstPhotos })
      .then((clusters) => {
        const tagMap: Record<string, string> = {};
        const bestShots = new Set<string>();

        let burstNum = 1;
        for (const cluster of clusters) {
          if (cluster.is_burst) {
            const tag = `B${burstNum++}`;
            for (const p of cluster.photos) {
              tagMap[p.path] = tag;
            }
            const bestGroup = photoGroups.find((g) => g.representative === cluster.best_shot);
            if (bestGroup) {
              bestShots.add(bestGroup.stem);
            }
          }
        }

        setBurstClusterMap(tagMap);
        setBestShotStems(bestShots);
      })
      .catch((err) => {
        console.error("Failed to compute burst clusters:", err);
      });
  }, [thumbnails, photoGroups]);

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

  // Stage a triage decision (Keep, Nah, Flag)
  const handleStageDecision = useCallback(
    async (decision: "keep" | "nah" | "flag") => {
      if (!activeGroup) return;

      try {
        const updated = await invoke<Record<string, string>>("stage_decision", {
          stem: activeGroup.stem,
          decision,
        });
        setStagedDecisions(updated);

        // Advance to next photo group
        setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1));
      } catch (err) {
        console.error("Failed to stage decision:", err);
      }
    },
    [activeGroup, photoGroups.length]
  );

  // Undo last decision
  const handleUndo = useCallback(async () => {
    try {
      const undoneStem = await invoke<string | null>("undo_decision");
      if (undoneStem) {
        const decisions = await invoke<Record<string, string>>("get_staged_decisions");
        setStagedDecisions(decisions);

        // Navigate back to the photo that was undone
        const foundIdx = photoGroups.findIndex((g) => g.stem === undoneStem);
        if (foundIdx !== -1) {
          setActiveIndex(foundIdx);
        }
      }
    } catch (err) {
      console.error("Failed to undo decision:", err);
    }
  }, [photoGroups]);

  // Open the review batch commit modal
  const handleOpenReviewModal = useCallback(async () => {
    try {
      const summary = await invoke<BatchSummaryDto>("get_batch_summary");
      setBatchSummary(summary);
      setIsModalOpen(true);
    } catch (err) {
      console.error("Failed to fetch batch summary:", err);
    }
  }, []);

  // Execute batch commit
  const handleConfirmCommit = async (actionMode: "move" | "copy") => {
    try {
      const result = await invoke<CommitResultDto>("commit_batch", {
        actionMode,
      });

      if (result.errors.length > 0) {
        alert(`Batch commit encountered errors:\n${result.errors.join("\n")}`);
      } else {
        // Re-scan directory to update queue
        if (selectedFolder) {
          await loadFolder(selectedFolder);
        }
      }
    } catch (err) {
      alert(`Commit error: ${err}`);
      console.error("Failed to execute batch commit:", err);
    }
  };

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

  // Global Keyboard Navigation & Hotkeys
  const handleSelectMember = useCallback(
    async (stem: string, memberPath: string) => {
      setActiveMemberOverride((prev) => ({ ...prev, [stem]: memberPath }));
      if (isRawFile(memberPath) && !resolvedPreviewMap[memberPath]) {
        try {
          const resolved = await invoke<string>("resolve_photo_preview", { path: memberPath });
          setResolvedPreviewMap((prev) => ({
            ...prev,
            [memberPath]: resolved || memberPath,
          }));
        } catch (err) {
          console.error("Failed to resolve photo preview:", err);
          setResolvedPreviewMap((prev) => ({ ...prev, [memberPath]: memberPath }));
        }
      }
    },
    [resolvedPreviewMap]
  );

  const selectedPrimaryMember = activeGroup
    ? activeMemberOverride[activeGroup.stem] || activeGroup.representative
    : "";

  const viewableMembers = activeGroup ? activeGroup.members.filter(isViewableFormat) : [];
  const hasMultipleFormats = viewableMembers.length > 1;

  // Companion format for 2-Up format comparison mode
  const companionFormatPath =
    compareTarget === "format" && hasMultipleFormats && activeGroup
      ? comparisonMemberOverride[activeGroup.stem] ||
        viewableMembers.find((m) => m !== selectedPrimaryMember) ||
        viewableMembers[0]
      : null;

  useEffect(() => {
    if (
      selectedPrimaryMember &&
      isRawFile(selectedPrimaryMember) &&
      !resolvedPreviewMap[selectedPrimaryMember]
    ) {
      invoke<string>("resolve_photo_preview", { path: selectedPrimaryMember })
        .then((resolved) => {
          setResolvedPreviewMap((prev) => ({
            ...prev,
            [selectedPrimaryMember]: resolved || selectedPrimaryMember,
          }));
        })
        .catch((err) => {
          console.error("Failed to resolve photo preview:", err);
          setResolvedPreviewMap((prev) => ({
            ...prev,
            [selectedPrimaryMember]: selectedPrimaryMember,
          }));
        });
    }
  }, [selectedPrimaryMember, resolvedPreviewMap]);

  useEffect(() => {
    if (
      companionFormatPath &&
      isRawFile(companionFormatPath) &&
      !resolvedPreviewMap[companionFormatPath]
    ) {
      invoke<string>("resolve_photo_preview", { path: companionFormatPath })
        .then((res) => {
          setResolvedPreviewMap((prev) => ({
            ...prev,
            [companionFormatPath]: res || companionFormatPath,
          }));
        })
        .catch((err) => {
          console.error("Failed to resolve companion photo preview:", err);
          setResolvedPreviewMap((prev) => ({
            ...prev,
            [companionFormatPath]: companionFormatPath,
          }));
        });
    }
  }, [companionFormatPath, resolvedPreviewMap]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // ⌘↵ / Ctrl+Enter: Review Batch Modal
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        if (Object.keys(stagedDecisions).length > 0) {
          handleOpenReviewModal();
        }
        return;
      }

      // Undo: ⌘Z / Ctrl+Z
      if ((e.metaKey || e.ctrlKey) && (e.key === "z" || e.key === "Z")) {
        e.preventDefault();
        handleUndo();
        return;
      }

      if (photoGroups.length === 0 || isModalOpen) return;

      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setActiveIndex((prev) => Math.max(0, prev - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setActiveIndex((prev) => Math.min(photoGroups.length - 1, prev + 1));
      } else if (e.key === "1") {
        e.preventDefault();
        handleStageDecision("keep");
      } else if (e.key === "2") {
        e.preventDefault();
        handleStageDecision("nah");
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        handleStageDecision("flag");
      } else if (e.key === "c" || e.key === "C") {
        e.preventDefault();
        setViewMode((prev) => (prev === "1-up" ? "2-up" : "1-up"));
      } else if (e.key === "x" || e.key === "X") {
        e.preventDefault();
        if (hasMultipleFormats) {
          if (viewMode !== "2-up") {
            setViewMode("2-up");
            setCompareTarget("format");
          } else {
            setCompareTarget((prev) => (prev === "photo" ? "format" : "photo"));
          }
        }
      } else if (e.key === "v" || e.key === "V") {
        e.preventDefault();
        if (activeGroup && hasMultipleFormats) {
          const current = activeMemberOverride[activeGroup.stem] || activeGroup.representative;
          const currentIdx = viewableMembers.indexOf(current);
          const nextIdx = (currentIdx + 1) % viewableMembers.length;
          const nextPath = viewableMembers[nextIdx];
          handleSelectMember(activeGroup.stem, nextPath);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    photoGroups.length,
    stagedDecisions,
    isModalOpen,
    activeGroup,
    activeMemberOverride,
    hasMultipleFormats,
    viewMode,
    viewableMembers,
    handleStageDecision,
    handleUndo,
    handleOpenReviewModal,
    handleSelectMember,
  ]);

  // Resolve comparison photo in 2-Up mode
  const comparisonGroup = (() => {
    if (!activeGroup || photoGroups.length < 2) return null;

    const activeBurstTag =
      burstClusterMap[activeGroup.representative] || burstClusterMap[activeGroup.stem];
    if (activeBurstTag) {
      // Find other photos in the same burst cluster
      const clusterMembers = photoGroups.filter(
        (g) =>
          (burstClusterMap[g.representative] === activeBurstTag ||
            burstClusterMap[g.stem] === activeBurstTag) &&
          g.stem !== activeGroup.stem
      );

      if (clusterMembers.length > 0) {
        // Prefer the Best Shot member in the cluster
        const bestShotMember = clusterMembers.find((g) => bestShotStems.has(g.stem));
        return bestShotMember || clusterMembers[0];
      }
    }

    // Default to adjacent photo
    return photoGroups[activeIndex + 1] || photoGroups[activeIndex - 1] || null;
  })();

  const primaryViewItem = activeGroup
    ? {
        filePath: resolvedPreviewMap[selectedPrimaryMember] || selectedPrimaryMember,
        stem: activeGroup.stem,
        exif: exifCache[activeGroup.representative] ?? null,
        isBestShot: bestShotStems.has(activeGroup.stem),
        burstTag:
          burstClusterMap[activeGroup.representative] || burstClusterMap[activeGroup.stem],
        members: activeGroup.members,
        selectedMember: selectedPrimaryMember,
        onSelectMember: (path: string) => handleSelectMember(activeGroup.stem, path),
      }
    : undefined;

  const comparisonViewItem = (() => {
    if (viewMode !== "2-up" || !activeGroup) return null;

    if (compareTarget === "format" && hasMultipleFormats && companionFormatPath) {
      return {
        filePath: resolvedPreviewMap[companionFormatPath] || companionFormatPath,
        stem: activeGroup.stem,
        exif: exifCache[activeGroup.representative] ?? null,
        isBestShot: false,
        burstTag: undefined,
        members: activeGroup.members,
        selectedMember: companionFormatPath,
        onSelectMember: (path: string) => {
          setComparisonMemberOverride((prev) => ({
            ...prev,
            [activeGroup.stem]: path,
          }));
          if (isRawFile(path) && !resolvedPreviewMap[path]) {
            invoke<string>("resolve_photo_preview", { path })
              .then((res) => {
                setResolvedPreviewMap((prev) => ({ ...prev, [path]: res || path }));
              })
              .catch((err) => {
                console.error(err);
                setResolvedPreviewMap((prev) => ({ ...prev, [path]: path }));
              });
          }
        },
      };
    }

    if (!comparisonGroup) return null;
    return {
      filePath: comparisonGroup.representative,
      stem: comparisonGroup.stem,
      exif: exifCache[comparisonGroup.representative] ?? null,
      isBestShot: bestShotStems.has(comparisonGroup.stem),
      burstTag:
        burstClusterMap[comparisonGroup.representative] ||
        burstClusterMap[comparisonGroup.stem],
      members: comparisonGroup.members,
      selectedMember: comparisonGroup.representative,
    };
  })();

  const totalStaged = Object.keys(stagedDecisions).length;
  const keepCount = Object.values(stagedDecisions).filter((d) => d === "keep").length;
  const nahCount = Object.values(stagedDecisions).filter((d) => d === "nah").length;

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

        {/* Right: View Mode, Staged Counts, Undo, Review Batch, and Actions */}
        <div className="flex items-center gap-2">
          {photoGroups.length > 1 && (
            <div className="flex items-center p-0.5 rounded-lg bg-zinc-900 border border-white/[0.08]">
              <button
                data-testid="view-mode-1up"
                onClick={() => setViewMode("1-up")}
                title="1-Up Single Viewport"
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition cursor-pointer ${
                  viewMode === "1-up"
                    ? "bg-zinc-800 text-white shadow-sm"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <Square className="w-3.5 h-3.5" />
                <span>1-Up</span>
              </button>
              <button
                data-testid="view-mode-2up"
                onClick={() => setViewMode("2-up")}
                title="2-Up Split Comparison Viewport (C)"
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition cursor-pointer ${
                  viewMode === "2-up"
                    ? "bg-zinc-800 text-white shadow-sm"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <Columns2 className="w-3.5 h-3.5" />
                <span>2-Up Compare</span>
              </button>
            </div>
          )}

          {totalStaged > 0 && (
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-zinc-900 border border-white/[0.08] text-xs font-mono">
              <span className="text-emerald-400 font-semibold">{keepCount} Keep</span>
              <span className="text-zinc-600">·</span>
              <span className="text-red-400 font-semibold">{nahCount} Nah</span>
            </div>
          )}

          <button
            onClick={handleUndo}
            disabled={totalStaged === 0}
            title="Undo last triage decision (⌘Z / Ctrl+Z)"
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-medium transition disabled:opacity-30 disabled:pointer-events-none border border-white/[0.06] active:scale-95 cursor-pointer"
          >
            <Undo2 className="w-3.5 h-3.5" />
            <span>Undo</span>
          </button>

          {totalStaged > 0 && (
            <button
              onClick={handleOpenReviewModal}
              title="Review and commit batch (⌘↵ / Ctrl+Enter)"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-accent hover:bg-accent-hover text-white text-xs font-semibold shadow-md shadow-accent/20 transition active:scale-95 cursor-pointer"
            >
              <CheckSquare className="w-3.5 h-3.5" />
              <span>Review Batch ({totalStaged})</span>
              <kbd className="px-1.5 py-0.5 rounded bg-black/25 text-blue-200 text-[10px] font-mono leading-none">
                ⌘↵
              </kbd>
            </button>
          )}

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
              viewMode={viewMode}
              primary={primaryViewItem}
              comparison={comparisonViewItem}
              compareTarget={compareTarget}
              onToggleCompareTarget={setCompareTarget}
              hasMultipleFormats={hasMultipleFormats}
            />

            {/* Floating Glass Action HUD */}
            <ActionHud
              onKeep={() => handleStageDecision("keep")}
              onNah={() => handleStageDecision("nah")}
              onFlag={() => handleStageDecision("flag")}
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
      <ThumbnailStrip
        groups={photoGroups}
        activeIndex={activeIndex}
        thumbnails={thumbnails}
        stagedDecisions={stagedDecisions}
        onSelect={(idx) => setActiveIndex(idx)}
        bestShotStems={bestShotStems}
        burstClusterMap={burstClusterMap}
      />

      {/* Review & Batch Commit Modal Sheet */}
      <ReviewCommitModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        summary={batchSummary}
        onConfirmCommit={handleConfirmCommit}
      />

      {/* Studio Footer Status */}
      <footer className="h-7 bg-panel border-t border-white/[0.06] flex items-center justify-between px-3 text-[11px] text-zinc-500 select-none shrink-0 font-mono">
        <div className="flex items-center gap-3">
          <span>Tauri v2 · Native Desktop</span>
          {photoGroups.length > 0 && (
            <span>Shortcuts: 1 Keep · 2 Nah · F Flag · C Compare · ⌘Z Undo · ⌘↵ Review Batch · 0 Fit</span>
          )}
        </div>
        <span>
          {photoGroups.length > 0
            ? `Photo ${activeIndex + 1} of ${photoGroups.length} (${totalStaged} staged)`
            : "Ready"}
        </span>
      </footer>
    </div>
  );
}
