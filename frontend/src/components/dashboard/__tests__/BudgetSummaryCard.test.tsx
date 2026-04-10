import { render, screen } from "../../../__tests__/test-utils";
import { describe, it, expect, vi } from "vitest";
import { BudgetSummaryCard } from "../BudgetSummaryCard";

describe("BudgetSummaryCard", () => {
  const defaultProps = {
    remaining: 1200,
    planned: 5000,
    spent: 3800,
    income: 5000,
    onAddTransaction: vi.fn(),
  };

  it("renders budget figures correctly", () => {
    render(<BudgetSummaryCard {...defaultProps} />);
    
    expect(screen.getByText(/1.*200,00.*zł/i)).toBeInTheDocument();
    expect(screen.getByText(/z 5.*000.*PLN przychodów/i)).toBeInTheDocument();
    expect(screen.getByText(/5.*000,00.*zł/i)).toBeInTheDocument();
    expect(screen.getByText(/3.*800,00.*zł/i)).toBeInTheDocument();
  });

  it("shows empty state CTA when no budget is set", () => {
    render(<BudgetSummaryCard {...defaultProps} planned={0} spent={0} income={0} />);
    
    expect(screen.getByText(/Brak transakcji w tym miesiącu/i)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /Dodaj transakcję/i });
    expect(btn).toBeInTheDocument();
  });

  it("highlights remaining amount in red when over budget", () => {
    render(<BudgetSummaryCard {...defaultProps} remaining={-500} />);
    
    const remainingText = screen.getByText(/-500,00.*zł/i);
    expect(remainingText).toHaveClass("text-destructive");
  });
});
