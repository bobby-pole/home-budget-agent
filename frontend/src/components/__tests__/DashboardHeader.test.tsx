import { render, screen } from "../../__tests__/test-utils"
import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { DashboardHeader } from "../DashboardHeader"
import { SidebarProvider } from "../ui/sidebar"
import { AuthProvider } from "../../context/AuthContext"
import { MemoryRouter } from "react-router-dom"

describe("DashboardHeader", () => {
  beforeEach(() => {
    localStorage.setItem("budget_user", JSON.stringify({ email: "test@example.com" }))
  })

  afterEach(() => {
    localStorage.removeItem("budget_user")
  })

  it("should show dynamic page title", () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1024 });
    
    render(
      <MemoryRouter initialEntries={["/dashboard"]}>
        <AuthProvider>
          <SidebarProvider>
            <DashboardHeader />
          </SidebarProvider>
        </AuthProvider>
      </MemoryRouter>
    );
    
    expect(screen.getByText(/Dashboard/i)).toBeInTheDocument();
  });

  it("should show user avatar and dropdown menu", () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1024 });
    
    render(
      <MemoryRouter>
        <AuthProvider>
          <SidebarProvider>
            <DashboardHeader />
          </SidebarProvider>
        </AuthProvider>
      </MemoryRouter>
    );
    
    expect(screen.getByText("TE")).toBeInTheDocument();
  });

  it("should show sidebar trigger on mobile", () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 500 });
    
    render(
      <MemoryRouter>
        <AuthProvider>
          <SidebarProvider>
            <DashboardHeader />
          </SidebarProvider>
        </AuthProvider>
      </MemoryRouter>
    );
    
    const trigger = screen.getByRole("button", { name: /toggle sidebar/i });
    expect(trigger).toBeInTheDocument();
  });
});
