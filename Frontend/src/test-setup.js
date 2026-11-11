import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })));
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.spyOn(window, "confirm").mockReturnValue(true);
  Element.prototype.scrollIntoView = vi.fn();
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
