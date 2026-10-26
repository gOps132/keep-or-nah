import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import {
  SettingsModal,
  loadStoredSettings,
  saveStoredSettings,
  DEFAULT_SETTINGS,
  DEFAULT_FORMAT_PRIORITY,
  AppSettings,
} from "./SettingsModal";

describe("SettingsModal & Preference Persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("loads default settings when localStorage is empty", () => {
    const loaded = loadStoredSettings();
    expect(loaded.defaultViewMode).toBe("1-up");
    expect(loaded.formatPriority).toEqual(DEFAULT_FORMAT_PRIORITY);
  });

  it("saves and reloads settings from localStorage", () => {
    const custom: AppSettings = {
      defaultViewMode: "2-up",
      formatPriority: [".png", ".jpg", ".arw"],
    };
    saveStoredSettings(custom);
    const loaded = loadStoredSettings();
    expect(loaded.defaultViewMode).toBe("2-up");
    expect(loaded.formatPriority).toEqual([".png", ".jpg", ".arw"]);
  });

  it("renders modal and closes on close button click and Escape key", () => {
    const onClose = vi.fn();
    const onUpdate = vi.fn();

    const { rerender } = render(
      <SettingsModal
        isOpen={true}
        onClose={onClose}
        settings={DEFAULT_SETTINGS}
        onUpdateSettings={onUpdate}
      />
    );

    expect(screen.getByTestId("settings-modal")).toBeDefined();
    expect(screen.getByText("Preferences")).toBeDefined();

    // Click close button
    fireEvent.click(screen.getByTestId("settings-close-btn"));
    expect(onClose).toHaveBeenCalledTimes(1);

    // Escape key closes modal
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);

    // When isOpen is false, nothing is rendered
    rerender(
      <SettingsModal
        isOpen={false}
        onClose={onClose}
        settings={DEFAULT_SETTINGS}
        onUpdateSettings={onUpdate}
      />
    );
    expect(screen.queryByTestId("settings-modal")).toBeNull();
  });

  it("allows selecting default view mode", () => {
    const onUpdate = vi.fn();
    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        settings={DEFAULT_SETTINGS}
        onUpdateSettings={onUpdate}
      />
    );

    // Click 2-Up option
    fireEvent.click(screen.getByTestId("setting-mode-2up"));
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ defaultViewMode: "2-up" })
    );

    const stored = loadStoredSettings();
    expect(stored.defaultViewMode).toBe("2-up");
  });

  it("reorders format priority up and down", () => {
    let currentSettings = { ...DEFAULT_SETTINGS };
    const onUpdate = vi.fn((newSettings) => {
      currentSettings = newSettings;
    });

    const { rerender } = render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        settings={currentSettings}
        onUpdateSettings={onUpdate}
      />
    );

    // Format priority starts with .jpg at index 0, .jpeg at index 1
    expect(currentSettings.formatPriority[0]).toBe(".jpg");
    expect(currentSettings.formatPriority[1]).toBe(".jpeg");

    // Move .jpeg up to index 0
    const moveJpegUp = screen.getByTestId("priority-up-jpeg");
    fireEvent.click(moveJpegUp);

    expect(onUpdate).toHaveBeenCalled();
    expect(currentSettings.formatPriority[0]).toBe(".jpeg");
    expect(currentSettings.formatPriority[1]).toBe(".jpg");

    rerender(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        settings={currentSettings}
        onUpdateSettings={onUpdate}
      />
    );

    // Click Reset to restore defaults
    fireEvent.click(screen.getByTestId("settings-reset-btn"));
    expect(currentSettings.formatPriority).toEqual(DEFAULT_FORMAT_PRIORITY);
  });
});
