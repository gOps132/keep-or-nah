import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ActionHud } from "./ActionHud";

describe("ActionHud Component", () => {
  it("renders Keep, Nah, and Flag buttons with keyboard tags", () => {
    let action = "";
    render(
      <ActionHud
        onKeep={() => {
          action = "keep";
        }}
        onNah={() => {
          action = "nah";
        }}
        onFlag={() => {
          action = "flag";
        }}
      />
    );

    expect(screen.getByText("Keep")).toBeDefined();
    expect(screen.getByText("Nah")).toBeDefined();
    expect(screen.getByText("Flag")).toBeDefined();

    fireEvent.click(screen.getByText("Keep"));
    expect(action).toBe("keep");

    fireEvent.click(screen.getByText("Nah"));
    expect(action).toBe("nah");

    fireEvent.click(screen.getByText("Flag"));
    expect(action).toBe("flag");
  });
});
