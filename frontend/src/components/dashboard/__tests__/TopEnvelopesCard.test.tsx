import { render, screen } from "../../../__tests__/test-utils";
import { describe, it, expect } from "vitest";
import { TopEnvelopesCard } from "../TopEnvelopesCard";

describe("TopEnvelopesCard", () => {
  const mockEnvelopes = [
    { id: 1, name: "Jedzenie", spent: 800, limit: 1000, color: "#ff0000" },
    { id: 2, name: "Rozrywka", spent: 1200, limit: 1000, color: "#00ff00" },
  ];

  it("renders envelopes with progress percentage", () => {
    render(<TopEnvelopesCard envelopes={mockEnvelopes} isLoading={false} />);
    
    expect(screen.getByText("Jedzenie")).toBeInTheDocument();
    expect(screen.getByText("80% wykorzystano")).toBeInTheDocument();
    
    expect(screen.getByText("Rozrywka")).toBeInTheDocument();
    expect(screen.getByText("100% wykorzystano")).toBeInTheDocument();
    expect(screen.getByText(/Przekroczono!/i)).toBeInTheDocument();
  });

  it("shows empty state when no envelopes", () => {
    render(<TopEnvelopesCard envelopes={[]} isLoading={false} />);
    expect(screen.getByText(/Brak ustawionych limitów/i)).toBeInTheDocument();
  });
});
