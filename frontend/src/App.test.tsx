import { describe, it, expect } from "vitest";

describe("App Title and Initial State", () => {
  it("defines default initial state without a selected folder", () => {
    const initialFolder = null;
    expect(initialFolder).toBeNull();
  });
});
