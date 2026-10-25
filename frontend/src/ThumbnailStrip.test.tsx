import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThumbnailStrip } from "./ThumbnailStrip";
import { PhotoGroup } from "./types";

const mockGroups: PhotoGroup[] = [
  { stem: "DSC_1001", members: ["DSC_1001.JPG"], representative: "DSC_1001.JPG", index: 0 },
  { stem: "DSC_1002", members: ["DSC_1002.JPG", "DSC_1002.RAW"], representative: "DSC_1002.JPG", index: 1 },
];

describe("ThumbnailStrip Component", () => {
  it("renders all photo groups in the strip and handles selection", () => {
    let selected = 0;
    render(
      <ThumbnailStrip
        groups={mockGroups}
        activeIndex={0}
        thumbnails={{}}
        stagedDecisions={{ DSC_1001: "keep" }}
        onSelect={(idx) => {
          selected = idx;
        }}
        bestShotStems={new Set(["DSC_1001"])}
      />
    );

    expect(screen.getByText("DSC_1001")).toBeDefined();
    expect(screen.getByText("DSC_1002")).toBeDefined();

    // Click second item
    fireEvent.click(screen.getByText("DSC_1002"));
    expect(selected).toBe(1);
  });
});
