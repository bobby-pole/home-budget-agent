import { render, screen } from "../../__tests__/test-utils"
import { describe, it, expect, vi } from "vitest"
import { AppSidebar } from "../AppSidebar"
import { MemoryRouter } from "react-router-dom"
import { SidebarProvider } from "../ui/sidebar"

// Mockujemy api aby kontrolować badge AI Inbox
vi.mock("@/lib/api", () => ({
  api: {
    getTransactions: vi.fn().mockResolvedValue([
      { id: 1, total_amount: 100, receipt_scan: { status: "processing" } },
      { id: 2, total_amount: 200, receipt_scan: { status: "done" } },
      { id: 3, total_amount: 300, receipt_scan: { status: "pending" } },
    ])
  }
}))

describe("AppSidebar", () => {
  const renderSidebar = () => {
    return render(
      <MemoryRouter>
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      </MemoryRouter>
    )
  }

  it("should render navigation items", async () => {
    renderSidebar();
    
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Budget")).toBeInTheDocument();
    expect(screen.getByText("Transactions")).toBeInTheDocument();
    expect(screen.getByText("AI Inbox")).toBeInTheDocument();
  });

  it("should show pending scans count in badge", async () => {
    renderSidebar();
    
    // Oczekujemy 2 (jeden processing, jeden pending)
    const badge = await screen.findByText("2");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("bg-destructive");
  });

  it("should show app name when expanded", () => {
    renderSidebar();
    expect(screen.getByText("Smart Budget")).toBeInTheDocument();
  });
});
