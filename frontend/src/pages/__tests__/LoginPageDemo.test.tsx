import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LoginPage } from "@/pages/LoginPage";

const mockLogin = vi.fn();
const mockLoginDemo = vi.fn();
const mockNavigate = vi.fn();
const mockUseAuth = vi.fn();

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe("LoginPage in Demo Mode", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_DEMO_MODE", "true");
    mockUseAuth.mockReturnValue({
      token: null,
      login: mockLogin,
      loginDemo: mockLoginDemo,
      isDemo: true,
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders demo showcase card and button when VITE_DEMO_MODE is true", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/wersja demonstracyjna/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /wypróbuj wersję demonstracyjną/i })).toBeInTheDocument();
    expect(screen.getByText(/zaloguj się tradycyjnie/i)).toBeInTheDocument();
  });

  it("calls loginDemo when clicking demo button", async () => {
    const user = userEvent.setup();
    mockLoginDemo.mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>
    );

    await user.click(screen.getByRole("button", { name: /wypróbuj wersję demonstracyjną/i }));

    await waitFor(() => {
      expect(mockLoginDemo).toHaveBeenCalled();
    });
  });

  it("toggles traditional login form on link click", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>
    );

    expect(screen.queryByLabelText(/hasło/i)).not.toBeInTheDocument();

    await user.click(screen.getByText(/zaloguj się tradycyjnie/i));

    expect(screen.getByLabelText(/hasło/i)).toBeInTheDocument();
  });

  it("auto-triggers loginDemo when query param demo=true is present", async () => {
    mockLoginDemo.mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/login?demo=true"]}>
        <LoginPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockLoginDemo).toHaveBeenCalled();
    });
  });
});
