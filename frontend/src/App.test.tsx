import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import App from "./App";
import { PhotoGroup, BatchSummaryDto } from "./types";

// Mock Tauri core IPC invoke and event listen
const mockPhotoGroups: PhotoGroup[] = [
  {
    stem: "DSC_0001",
    members: ["/photos/DSC_0001.JPG", "/photos/DSC_0001.ARW"],
    representative: "/photos/DSC_0001.JPG",
    index: 0,
  },
  {
    stem: "DSC_0002",
    members: ["/photos/DSC_0002.JPG"],
    representative: "/photos/DSC_0002.JPG",
    index: 1,
  },
  {
    stem: "DSC_0003",
    members: ["/photos/DSC_0003.JPG"],
    representative: "/photos/DSC_0003.JPG",
    index: 2,
  },
];

let stagedMap: Record<string, string> = {};

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => false,
  convertFileSrc: (p: string) => `asset://${p}`,
  invoke: vi.fn(async (cmd: string, args?: any) => {
    switch (cmd) {
      case "open_directory_dialog":
        return "/photos";
      case "scan_directory":
        return mockPhotoGroups;
      case "start_thumbnail_stream":
        return null;
      case "resolve_photo_preview":
        return args.path;
      case "read_exif_metadata":
        return {
          camera_model: "Sony A7IV",
          shutter_speed: "1/500s",
          aperture: "f/2.8",
          iso: "ISO 400",
          focal_length: "50mm",
          lens_model: "FE 50mm F1.2 GM",
        };
      case "stage_decision": {
        stagedMap[args.stem] = args.decision;
        return { ...stagedMap };
      }
      case "undo_decision": {
        const keys = Object.keys(stagedMap);
        if (keys.length > 0) {
          const lastKey = keys[keys.length - 1];
          delete stagedMap[lastKey];
          return lastKey;
        }
        return null;
      }
      case "get_staged_decisions":
        return { ...stagedMap };
      case "get_batch_summary": {
        const summary: BatchSummaryDto = {
          total_groups: Object.keys(stagedMap).length,
          keep_count: Object.values(stagedMap).filter((d) => d === "keep").length,
          nah_count: Object.values(stagedMap).filter((d) => d === "nah").length,
          flag_count: Object.values(stagedMap).filter((d) => d === "flag").length,
          total_files: Object.keys(stagedMap).length,
          total_reclaimed_bytes: 10485760,
          items: Object.entries(stagedMap).map(([stem, decision]) => ({
            stem,
            decision,
            file_count: 1,
            total_bytes: 5242880,
          })),
        };
        return summary;
      }
      case "commit_batch":
        stagedMap = {};
        return { successful_groups: 2, successful_files: 2, errors: [] };
      case "compute_burst_clusters":
        return [];
      default:
        return null;
    }
  }),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => {}),
}));

describe("App Integration Tests", () => {
  beforeEach(() => {
    stagedMap = {};
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders empty state when no folder is selected", () => {
    render(<App />);
    expect(screen.getByText("No Photo Session Loaded")).toBeDefined();
    expect(screen.getByText("Choose Photo Folder")).toBeDefined();
  });

  it("loads photo directory on Choose Photo Folder click", async () => {
    render(<App />);
    const openBtn = screen.getByText("Choose Photo Folder");
    fireEvent.click(openBtn);

    await waitFor(() => {
      expect(screen.getByText("DSC_0001")).toBeDefined();
      expect(screen.getByText("DSC_0002")).toBeDefined();
      expect(screen.getByText("DSC_0003")).toBeDefined();
    });
  });

  it("handles keyboard navigation ArrowRight and ArrowLeft", async () => {
    render(<App />);
    fireEvent.click(screen.getByText("Choose Photo Folder"));

    await waitFor(() => {
      expect(screen.getByText("DSC_0001")).toBeDefined();
    });

    // Press ArrowRight to advance to index 1 (DSC_0002)
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => {
      expect(screen.getByText(/Photo 2 of 3/)).toBeDefined();
    });

    // Press ArrowLeft to return to index 0 (DSC_0001)
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    await waitFor(() => {
      expect(screen.getByText(/Photo 1 of 3/)).toBeDefined();
    });
  });

  it("handles keyboard triage: 1 (Keep), 2 (Nah), F (Flag) and advances active index", async () => {
    render(<App />);
    fireEvent.click(screen.getByText("Choose Photo Folder"));

    await waitFor(() => {
      expect(screen.getByText("DSC_0001")).toBeDefined();
    });

    // Press 1 to Keep DSC_0001 -> advances to DSC_0002
    fireEvent.keyDown(window, { key: "1" });
    await waitFor(() => {
      expect(stagedMap["DSC_0001"]).toBe("keep");
      expect(screen.getByText(/Photo 2 of 3/)).toBeDefined();
    });

    // Press 2 to Nah DSC_0002 -> advances to DSC_0003
    fireEvent.keyDown(window, { key: "2" });
    await waitFor(() => {
      expect(stagedMap["DSC_0002"]).toBe("nah");
      expect(screen.getByText(/Photo 3 of 3/)).toBeDefined();
    });

    // Press F to Flag DSC_0003
    fireEvent.keyDown(window, { key: "f" });
    await waitFor(() => {
      expect(stagedMap["DSC_0003"]).toBe("flag");
    });
  });

  it("handles undo via ⌘Z keyboard shortcut", async () => {
    render(<App />);
    fireEvent.click(screen.getByText("Choose Photo Folder"));

    await waitFor(() => {
      expect(screen.getByText("DSC_0001")).toBeDefined();
    });

    // Stage Keep on DSC_0001
    fireEvent.keyDown(window, { key: "1" });
    await waitFor(() => {
      expect(stagedMap["DSC_0001"]).toBe("keep");
    });

    // Undo with ⌘Z
    fireEvent.keyDown(window, { key: "z", metaKey: true });
    await waitFor(() => {
      expect(stagedMap["DSC_0001"]).toBeUndefined();
    });
  });

  it("toggles split comparison view mode between 1-Up and 2-Up", async () => {
    render(<App />);
    fireEvent.click(screen.getByText("Choose Photo Folder"));

    await waitFor(() => {
      expect(screen.getByText("DSC_0001")).toBeDefined();
    });

    // Toggle 2-Up compare mode
    const compareBtn = screen.getByText("2-Up Compare");
    fireEvent.click(compareBtn);

    expect(screen.getByTestId("split-left-pane")).toBeDefined();
    expect(screen.getByTestId("split-right-pane")).toBeDefined();

    // Toggle back to 1-Up
    const oneUpBtn = screen.getByText("1-Up");
    fireEvent.click(oneUpBtn);

    expect(screen.getByTestId("single-pane")).toBeDefined();
  });

  it("opens review modal and commits batch", async () => {
    render(<App />);
    fireEvent.click(screen.getByText("Choose Photo Folder"));

    await waitFor(() => {
      expect(screen.getByText("DSC_0001")).toBeDefined();
    });

    // Stage Keep on DSC_0001
    fireEvent.keyDown(window, { key: "1" });
    await waitFor(() => {
      expect(stagedMap["DSC_0001"]).toBe("keep");
    });

    // Open review modal via header button
    const reviewBtn = screen.getByRole("button", { name: /Review Batch/i });
    fireEvent.click(reviewBtn);

    await waitFor(() => {
      expect(screen.getByText("Review Staged Decisions")).toBeDefined();
    });

    // Confirm commit
    const commitBtn = screen.getByRole("button", { name: /Commit 1 Staged Groups/i });
    fireEvent.click(commitBtn);

    await waitFor(() => {
      expect(screen.queryByText("Review Staged Decisions")).toBeNull();
    });
  });

  it("cycles active format within photo group on pressing V and format pill click", async () => {
    render(<App />);
    fireEvent.click(screen.getByText("Choose Photo Folder"));

    await waitFor(() => {
      expect(screen.getByText("DSC_0001")).toBeDefined();
    });

    // Format pills should render for DSC_0001 which has JPG and ARW
    await waitFor(() => {
      expect(screen.getByTestId("format-pill-jpg")).toBeDefined();
      expect(screen.getByTestId("format-pill-arw")).toBeDefined();
    });

    // Press V to cycle from JPG to ARW
    fireEvent.keyDown(window, { key: "v" });
    await waitFor(() => {
      const activePill = screen.getByTestId("format-pill-arw");
      expect(activePill.className).toContain("bg-accent");
    });

    // Click JPG pill to switch back
    fireEvent.click(screen.getByTestId("format-pill-jpg"));
    await waitFor(() => {
      const activePill = screen.getByTestId("format-pill-jpg");
      expect(activePill.className).toContain("bg-accent");
    });
  });
});
