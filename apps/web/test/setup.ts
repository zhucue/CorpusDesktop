import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom does not implement pseudo-element styles, which Ant Design measures for scrollbars.
const getComputedStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = (elt: Element) => getComputedStyle(elt);

// Ant Design reads matchMedia in jsdom.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
