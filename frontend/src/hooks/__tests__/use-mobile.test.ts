import { renderHook, act } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"
import { useIsMobile } from "../use-mobile"

describe("useIsMobile", () => {
  it("should return true when width is below 768px", () => {
    // Symulacja szerokości okna
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 500 });
    
    const { result } = renderHook(() => useIsMobile());
    
    expect(result.current).toBe(true);
  });

  it("should return false when width is 768px or above", () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1024 });
    
    // Manualnie odpalamy event listener jeśli potrzebny, ale hook sprawdza przy montowaniu
    const { result } = renderHook(() => useIsMobile());
    
    expect(result.current).toBe(false);
  });

  it("should update when window is resized", () => {
    let resizeCallback: () => void = () => {};
    
    // Mock dla addEventListener aby przechwycić callback 'change' (z matchMedia)
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn((event, cb) => {
        if (event === 'change') resizeCallback = cb as () => void;
      }),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1024 });
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    act(() => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 500 });
      resizeCallback();
    });

    expect(result.current).toBe(true);
  });
});
