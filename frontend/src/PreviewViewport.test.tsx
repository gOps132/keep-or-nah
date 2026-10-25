import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { PreviewViewport } from "./PreviewViewport";

describe("PreviewViewport Component", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders standard 1-Up single pane viewport", () => {
    render(
      <PreviewViewport
        filePath="/photos/DSC_001.JPG"
        stem="DSC_001"
        exif={{
          camera_model: "Sony A7IV",
          shutter_speed: "1/500s",
          aperture: "f/2.8",
          iso: "ISO 400",
          focal_length: "50mm",
          lens_model: null,
        }}
        viewMode="1-up"
      />
    );

    expect(screen.getByTestId("single-pane")).toBeDefined();
    expect(screen.queryByTestId("split-left-pane")).toBeNull();
    expect(screen.queryByTestId("split-right-pane")).toBeNull();
    expect(screen.getByText("Sony A7IV")).toBeDefined();
    expect(screen.getByText("100%")).toBeDefined();
  });

  it("renders side-by-side split 2-Up comparison viewport", () => {
    render(
      <PreviewViewport
        viewMode="2-up"
        primary={{
          filePath: "/photos/DSC_001.JPG",
          stem: "DSC_001",
          exif: {
            camera_model: "Sony A7IV",
            shutter_speed: "1/500s",
            aperture: null,
            iso: null,
            focal_length: null,
            lens_model: null,
          },
          burstTag: "B1",
          isBestShot: false,
        }}
        comparison={{
          filePath: "/photos/DSC_002.JPG",
          stem: "DSC_002",
          exif: null,
          burstTag: "B1",
          isBestShot: true,
        }}
      />
    );

    expect(screen.getByTestId("split-left-pane")).toBeDefined();
    expect(screen.getByTestId("split-right-pane")).toBeDefined();
    expect(screen.getByText("Active")).toBeDefined();
    expect(screen.getByText("★ Best Shot")).toBeDefined();
  });

  it("updates zoom percentage on zoom button click", () => {
    render(
      <PreviewViewport
        filePath="/photos/DSC_001.JPG"
        stem="DSC_001"
        exif={null}
        viewMode="1-up"
      />
    );

    expect(screen.getByText("100%")).toBeDefined();

    // Click Zoom In
    const zoomInBtn = screen.getByTitle("Zoom In (⌘ +)");
    fireEvent.click(zoomInBtn);
    expect(screen.getByText("125%")).toBeDefined();

    // Click Fit to Window (Reset)
    const fitBtn = screen.getByTitle("Fit to Window (0)");
    fireEvent.click(fitBtn);
    expect(screen.getByText("100%")).toBeDefined();
  });
});
