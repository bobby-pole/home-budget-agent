import { render, screen } from "../../__tests__/test-utils"
import { describe, it, expect } from "vitest"
import { DashboardHeader } from "../DashboardHeader"
import { SidebarProvider } from "../ui/sidebar"

describe("DashboardHeader", () => {
  it("should show app title on desktop", () => {
    // Desktop: isMobile = false
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1024 });
    
    render(
      <SidebarProvider>
        <DashboardHeader />
      </SidebarProvider>
    );
    
    expect(screen.getByText("Smart Budget AI")).toBeInTheDocument();
  });

  it("should show sidebar trigger on mobile", () => {
    // Mobile: isMobile = true
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 500 });
    
    render(
      <SidebarProvider>
        <DashboardHeader />
      </SidebarProvider>
    );
    
    const trigger = screen.getByRole("button", { name: /toggle sidebar/i });
    expect(trigger).toBeInTheDocument();
  });
});
