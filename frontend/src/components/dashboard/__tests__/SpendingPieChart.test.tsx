import { render, screen, fireEvent } from "../../../__tests__/test-utils";
import { describe, it, expect } from "vitest";
import { SpendingPieChart } from "../SpendingPieChart";
import { MemoryRouter } from "react-router-dom";

// Mock ResponsiveContainer since it doesn't work well in JSDOM
import { vi } from "vitest";
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div style={{ width: '100%', height: '100%' }}>{children}</div>,
  };
});

describe("SpendingPieChart", () => {
  const mockData = [
    { name: "Jedzenie", value: 500, color: "#ff0000" },
    { name: "Paliwo", value: 300, color: "#00ff00" },
  ];

  it("renders category list and total amount", () => {
    render(
      <MemoryRouter>
        <SpendingPieChart data={mockData} isLoading={false} />
      </MemoryRouter>
    );
    
    expect(screen.getByText("Jedzenie")).toBeInTheDocument();
    expect(screen.getByText("Paliwo")).toBeInTheDocument();
    expect(screen.getByText("800")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    render(
      <MemoryRouter>
        <SpendingPieChart data={[]} isLoading={true} />
      </MemoryRouter>
    );
    // Just check for the loading card/container
    expect(screen.queryByText("Wydatki miesięczne")).not.toBeInTheDocument();
  });

  it("shows empty state when no data", () => {
    render(
      <MemoryRouter>
        <SpendingPieChart data={[]} isLoading={false} />
      </MemoryRouter>
    );
    expect(screen.getByText(/Brak danych/i)).toBeInTheDocument();
  });

  it("allows excluding a category by clicking its legend item, recalculating percentages/totals and allowing to restore it", () => {
    render(
      <MemoryRouter>
        <SpendingPieChart data={mockData} isLoading={false} />
      </MemoryRouter>
    );

    // Initial state check
    expect(screen.getByText("Jedzenie")).toBeInTheDocument();
    expect(screen.getByText("Paliwo")).toBeInTheDocument();
    expect(screen.getByText("800")).toBeInTheDocument();

    // Click "Jedzenie" in legend
    const jedzenieBtn = screen.getByRole("button", { name: /Jedzenie/i });
    fireEvent.click(jedzenieBtn);

    // Total should update to 300 (only Paliwo remains)
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(screen.queryByText("800")).not.toBeInTheDocument();
    // Paliwo should now be 100%
    expect(screen.getByText("100%")).toBeInTheDocument();

    // Excluded section visible
    expect(screen.getByText("Wykluczone kategorie")).toBeInTheDocument();
    const excludedBadge = screen.getByRole("button", { name: /Jedzenie\+/i });
    expect(excludedBadge).toBeInTheDocument();

    // Restore "Jedzenie"
    fireEvent.click(excludedBadge);

    // Back to normal
    expect(screen.getByText("800")).toBeInTheDocument();
    expect(screen.queryByText("Wykluczone kategorie")).not.toBeInTheDocument();
  });

  it("allows restoring all excluded categories with a single click", () => {
    render(
      <MemoryRouter>
        <SpendingPieChart data={mockData} isLoading={false} />
      </MemoryRouter>
    );

    // Exclude both categories
    fireEvent.click(screen.getByRole("button", { name: /Jedzenie/i }));
    fireEvent.click(screen.getByRole("button", { name: /Paliwo/i }));

    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Wykluczone kategorie")).toBeInTheDocument();

    // Click "Przywróć wszystkie"
    const restoreAllBtn = screen.getByRole("button", { name: /Przywróć wszystkie/i });
    fireEvent.click(restoreAllBtn);

    expect(screen.getByText("800")).toBeInTheDocument();
    expect(screen.queryByText("Wykluczone kategorie")).not.toBeInTheDocument();
  });

  it("excludes underlying categories when clicking the Other slice/legend", () => {
    const mockMoreData = [
      { name: "Cat1", value: 100, color: "#1" },
      { name: "Cat2", value: 100, color: "#2" },
      { name: "Cat3", value: 100, color: "#3" },
      { name: "Cat4", value: 100, color: "#4" },
      { name: "Cat5", value: 100, color: "#5" },
      { name: "Cat6", value: 50, color: "#6" },
    ];

    render(
      <MemoryRouter>
        <SpendingPieChart data={mockMoreData} isLoading={false} />
      </MemoryRouter>
    );

    // "Inne" should be in legend (which is a button)
    expect(screen.getByRole("button", { name: /Inne/i })).toBeInTheDocument();

    // Click "Inne" button to exclude all items in it (Cat6)
    fireEvent.click(screen.getByRole("button", { name: /Inne/i }));

    // Cat6 should be excluded
    expect(screen.getByText("Wykluczone kategorie")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cat6\+/i })).toBeInTheDocument();

    // Total should update to 500 (550 - 50)
    expect(screen.getByText("500")).toBeInTheDocument();
  });

  it("normalizes percentages so they sum to exactly 100% (Largest Remainder Method)", () => {
    const mockTrioData = [
      { name: "Cat1", value: 10, color: "#1" },
      { name: "Cat2", value: 10, color: "#2" },
      { name: "Cat3", value: 10, color: "#3" },
    ];

    render(
      <MemoryRouter>
        <SpendingPieChart data={mockTrioData} isLoading={false} />
      </MemoryRouter>
    );

    // Sum is 30. Precise values are 33.33% each.
    // LRM normalization should distribute the remainder to make it: 34%, 33%, 33% (sum = 100%)
    expect(screen.getByText("34%")).toBeInTheDocument();
    expect(screen.getAllByText("33%")).toHaveLength(2);
  });
});
