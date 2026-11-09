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
    expect(screen.getByRole("button", { name: /uruchom wersję demonstracyjną/i })).toBeInTheDocument();
    expect(screen.getByText(/prywatne środowisko testowe/i)).toBeInTheDocument();
  });

  it("calls loginDemo when clicking demo button", async () => {
    const user = userEvent.setup();
    mockLoginDemo.mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>
    );

    await user.click(screen.getByRole("button", { name: /uruchom wersję demonstracyjną/i }));

    await waitFor(() => {
      expect(mockLoginDemo).toHaveBeenCalled();
    });
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

  it("switches language between Polish and English dynamically when clicking language button", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>
    );

    // Initially in Polish
    expect(screen.getByText(/wersja demonstracyjna/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /uruchom wersję demonstracyjną/i })).toBeInTheDocument();

    // Click English switch button
    const enButton = screen.getByRole("button", { name: /english/i });
    await user.click(enButton);

    // Now in English
    expect(screen.getByText("Rachownik – Demo Showcase")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /launch demo showcase/i })).toBeInTheDocument();
    expect(localStorage.getItem("app_locale")).toBe("en");

    // Click Polish switch button
    const plButton = screen.getByRole("button", { name: /polski/i });
    await user.click(plButton);

    // Back to Polish
    expect(screen.getByText("Rachownik – wersja demonstracyjna")).toBeInTheDocument();
    expect(localStorage.getItem("app_locale")).toBe("pl");
  });
});
