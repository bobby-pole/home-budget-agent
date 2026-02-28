import "@testing-library/jest-dom";
import { vi, afterEach } from "vitest";

// Polyfill dla Radix UI (wymaga ResizeObserver)
window.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Polyfill dla window.matchMedia (Radix UI, Theme detection)
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Polyfill dla crypto.randomUUID (jsdom może go nie mieć)
if (!window.crypto.randomUUID) {
  Object.defineProperty(window.crypto, "randomUUID", {
    value: () => `test-${Math.random().toString(36).slice(2)}`,
  });
}

// Czyść wszystkie mocki po każdym teście
afterEach(() => {
  vi.clearAllMocks();
});
