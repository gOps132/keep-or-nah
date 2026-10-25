import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { ReviewCommitModal } from "./ReviewCommitModal";
import { BatchSummaryDto } from "./types";

afterEach(() => {
  cleanup();
});

const mockSummary: BatchSummaryDto = {
  total_groups: 2,
  keep_count: 5,
  nah_count: 12,
  flag_count: 2,
  total_files: 17,
  total_reclaimed_bytes: 52428800, // 50 MB
  items: [
    {
      stem: "grp-1",
      decision: "keep",
      file_count: 1,
      total_bytes: 1048576,
    },
    {
      stem: "grp-2",
      decision: "nah",
      file_count: 3,
      total_bytes: 51380224,
    },
  ],
};

describe("ReviewCommitModal", () => {
  it("does not render when isOpen is false", () => {
    const { container } = render(
      <ReviewCommitModal
        isOpen={false}
        onClose={vi.fn()}
        summary={mockSummary}
        onConfirmCommit={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders correctly with summary statistics when open", () => {
    render(
      <ReviewCommitModal
        isOpen={true}
        onClose={vi.fn()}
        summary={mockSummary}
        onConfirmCommit={vi.fn()}
      />
    );

    expect(screen.getByText("Review Staged Decisions")).toBeDefined();
    expect(screen.getByText("5")).toBeDefined(); // keep_count
    expect(screen.getByText("12")).toBeDefined(); // nah_count
    expect(screen.getByText("50 MB")).toBeDefined(); // total_reclaimed_bytes
    expect(screen.getByText("grp-1")).toBeDefined();
    expect(screen.getByText("grp-2")).toBeDefined();
  });

  it("allows switching transfer mode between Move and Copy", () => {
    render(
      <ReviewCommitModal
        isOpen={true}
        onClose={vi.fn()}
        summary={mockSummary}
        onConfirmCommit={vi.fn()}
      />
    );

    const copyBtn = screen.getByText("Copy");
    fireEvent.click(copyBtn);
    expect(copyBtn.className).toContain("bg-zinc-800");

    const moveBtn = screen.getByText("Move from Source");
    fireEvent.click(moveBtn);
    expect(moveBtn.className).toContain("bg-zinc-800");
  });

  it("calls onConfirmCommit with selected action mode and closes", async () => {
    const onConfirmCommit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(
      <ReviewCommitModal
        isOpen={true}
        onClose={onClose}
        summary={mockSummary}
        onConfirmCommit={onConfirmCommit}
      />
    );

    const executeBtn = screen.getByRole("button", { name: /Commit 2 Staged Groups/i });
    fireEvent.click(executeBtn);

    await waitFor(() => {
      expect(onConfirmCommit).toHaveBeenCalledWith("move");
      expect(onClose).toHaveBeenCalled();
    });
  });
});
