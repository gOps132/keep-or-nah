import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ThumbnailStrip, resolveThumbnailUrl } from "./ThumbnailStrip";
import { PhotoGroup } from "./types";

const mockGroups: PhotoGroup[] = [
  { stem: "DSC_1001", members: ["DSC_1001.JPG"], representative: "DSC_1001.JPG", index: 0 },
  { stem: "DSC_1002", members: ["DSC_1002.JPG", "DSC_1002.RAW"], representative: "DSC_1002.JPG", index: 1 },
];

describe("ThumbnailStrip Component", () => {
  afterEach(() => {
    cleanup();
  });
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

  it("renders burst cluster tags and best shot badges", () => {
    render(
      <ThumbnailStrip
        groups={mockGroups}
        activeIndex={0}
        thumbnails={{}}
        stagedDecisions={{}}
        onSelect={() => {}}
        bestShotStems={new Set(["DSC_1001"])}
        burstClusterMap={{ DSC_1001: "B1", DSC_1002: "B1" }}
      />
    );

    expect(screen.getByTestId("burst-tag-DSC_1001").textContent).toBe("B1");
    expect(screen.getByTestId("burst-tag-DSC_1002").textContent).toBe("B1");
    expect(screen.getByTestId("best-shot-badge-DSC_1001")).toBeDefined();
    expect(screen.queryByTestId("best-shot-badge-DSC_1002")).toBeNull();
  });

  it("resolves thumbnail url prioritizing binary cache path over base64 data url", () => {
    expect(resolveThumbnailUrl(undefined)).toBeUndefined();

    // Cache path without base64 data_url
    const cachedThumb = {
      path: "/photos/DSC_001.JPG",
      cache_path: "/tmp/cache/thumb_001.jpg",
      src_url: "asset://localhost/tmp/cache/thumb_001.jpg",
      sharpness: 42.0,
      width: 160,
      height: 120,
    };
    expect(resolveThumbnailUrl(cachedThumb)).toBe("asset://localhost/tmp/cache/thumb_001.jpg");

    // Fallback to data_url if present
    const legacyThumb = {
      path: "/photos/DSC_002.JPG",
      data_url: "data:image/jpeg;base64,abc",
      sharpness: 10.0,
      width: 160,
      height: 120,
    };
    expect(resolveThumbnailUrl(legacyThumb)).toBe("data:image/jpeg;base64,abc");
  });
});
