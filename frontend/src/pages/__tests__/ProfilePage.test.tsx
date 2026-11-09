import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { ProfilePage } from "@/pages/ProfilePage";
import { MemoryRouter } from "react-router-dom";

let mockIsDemo = false;

// Mock AuthContext
vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, email: "test@example.com", name: "Test User", default_budget_id: 1 },
    activeBudgetId: 1,
    isDemo: mockIsDemo,
    switchBudget: vi.fn(),
    updateUser: vi.fn(),
    logout: vi.fn(),
  }),
}));

// Mock react-query useQuery
vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQuery: () => ({
      data: [
        { id: 1, name: "Test Budget", role: "owner" },
        { id: 2, name: "Shared Budget", role: "member" },
      ],
      isLoading: false,
    }),
    useMutation: () => ({
      mutate: vi.fn(),
      isPending: false,
    }),
  };
});

describe("ProfilePage", () => {
  it("renders correctly with budgets", () => {
    mockIsDemo = false;
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );
    // Should render headers from the locale
    expect(screen.getByText("Mój profil")).toBeInTheDocument();
    
    // Check if budgets are rendered
    expect(screen.getByText("Test Budget")).toBeInTheDocument();
    expect(screen.getByText("Shared Budget")).toBeInTheDocument();
  });

  it("disables budget modifications, invite, and password change in demo mode", () => {
    mockIsDemo = true;
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    // Change password button should be disabled
    const changePasswordBtn = screen.getByRole("button", { name: "Zmień hasło" });
    expect(changePasswordBtn).toBeDisabled();

    // Create budget button should be disabled
    const createBudgetBtn = screen.getByRole("button", { name: /utwórz budżet/i });
    expect(createBudgetBtn).toBeDisabled();

    // Invite button should be disabled
    const inviteBtn = screen.getByRole("button", { name: /zaproś/i });
    expect(inviteBtn).toBeDisabled();

    // In demo mode, disabled badge is shown
    expect(screen.getByText("Opcja zablokowana w wersji demo")).toBeInTheDocument();
  });
});
