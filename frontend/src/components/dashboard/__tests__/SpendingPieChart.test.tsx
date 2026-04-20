import { render, screen } from "../../../__tests__/test-utils";
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
        <SpendingPieChart data={mockData} isLoading={false} total={800} />
      </MemoryRouter>
    );
    
    expect(screen.getByText("Jedzenie")).toBeInTheDocument();
    expect(screen.getByText("Paliwo")).toBeInTheDocument();
    expect(screen.getByText("800")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    render(
      <MemoryRouter>
        <SpendingPieChart data={[]} isLoading={true} total={0} />
      </MemoryRouter>
    );
    // Just check for the loading card/container
    expect(screen.queryByText("Wydatki miesięczne")).not.toBeInTheDocument();
  });

  it("shows empty state when no data", () => {
    render(
      <MemoryRouter>
        <SpendingPieChart data={[]} isLoading={false} total={0} />
      </MemoryRouter>
    );
    expect(screen.getByText(/Brak danych/i)).toBeInTheDocument();
  });
});
