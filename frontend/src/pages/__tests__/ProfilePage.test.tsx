import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { ProfilePage } from "@/pages/ProfilePage";
import { MemoryRouter } from "react-router-dom";

// Mock AuthContext
vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, email: "test@example.com", name: "Test User", default_budget_id: 1 },
    activeBudgetId: 1,
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
});
