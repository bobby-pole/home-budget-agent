import { render, screen } from "../../../__tests__/test-utils";
import { describe, it, expect } from "vitest";
import { TopEnvelopesCard } from "../TopEnvelopesCard";
import { MemoryRouter } from "react-router-dom";

describe("TopEnvelopesCard", () => {
  const mockEnvelopes = [
    { id: 1, name: "Jedzenie", spent: 800, limit: 1000, color: "#ff0000", icon: "🍔" },
    { id: 2, name: "Rozrywka", spent: 1200, limit: 1000, color: "#00ff00", icon: "🎬" },
  ];

  it("renders envelopes with progress percentage", () => {
    render(
      <MemoryRouter>
        <TopEnvelopesCard envelopes={mockEnvelopes} isLoading={false} />
      </MemoryRouter>
    );
    
    expect(screen.getByText("Jedzenie")).toBeInTheDocument();
    expect(screen.getByText("Pozostało 200 PLN")).toBeInTheDocument();
    expect(screen.getAllByText(/z 1\s*000|z 1\.000|z 1000/)).toHaveLength(2);
    
    expect(screen.getByText("Rozrywka")).toBeInTheDocument();
    expect(screen.getByText("Pozostało 0 PLN")).toBeInTheDocument();
  });

  it("shows empty state when no envelopes", () => {
    render(
      <MemoryRouter>
        <TopEnvelopesCard envelopes={[]} isLoading={false} />
      </MemoryRouter>
    );
    expect(screen.getByText(/Brak ustawionych limitów/i)).toBeInTheDocument();
  });
});
