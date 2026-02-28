import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LoginPage } from "@/pages/LoginPage";

const mockLogin = vi.fn();
const mockNavigate = vi.fn();
const mockUseAuth = vi.fn();

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

function renderLoginPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ token: null, login: mockLogin });
  });

  it("renders email input", () => {
    renderLoginPage();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  });

  it("renders password input", () => {
    renderLoginPage();
    expect(screen.getByLabelText(/hasło/i)).toBeInTheDocument();
  });

  it("renders submit button with correct label", () => {
    renderLoginPage();
    expect(screen.getByRole("button", { name: /zaloguj się/i })).toBeInTheDocument();
  });

  it("renders link to register page", () => {
    renderLoginPage();
    expect(screen.getByRole("link", { name: /zarejestruj się/i })).toBeInTheDocument();
  });

  it("shows validation error for invalid email format", async () => {
    renderLoginPage();

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "not-an-email" } });
    fireEvent.change(screen.getByLabelText(/hasło/i), { target: { value: "password123" } });
    fireEvent.submit(screen.getByRole("button", { name: /zaloguj się/i }).closest("form")!);

    await waitFor(() => {
      expect(screen.getByText(/nieprawidłowy adres email/i)).toBeInTheDocument();
    });
  });

  it("shows validation error for empty password", async () => {
    const user = userEvent.setup();
    renderLoginPage();

    await user.type(screen.getByLabelText(/email/i), "test@example.com");
    await user.click(screen.getByRole("button", { name: /zaloguj się/i }));

    await waitFor(() => {
      expect(screen.getByText(/hasło jest wymagane/i)).toBeInTheDocument();
    });
  });

  it("already authenticated renders Navigate to /", () => {
    mockUseAuth.mockReturnValue({ token: "existing-token", login: mockLogin });
    renderLoginPage();
    // LoginPage renders Navigate which replaces the current route — page content is gone
    expect(screen.queryByRole("button", { name: /zaloguj się/i })).not.toBeInTheDocument();
  });

  it("calls auth.login with email and password on submit", async () => {
    const user = userEvent.setup();
    mockLogin.mockResolvedValue(undefined);
    renderLoginPage();

    await user.type(screen.getByLabelText(/email/i), "test@example.com");
    await user.type(screen.getByLabelText(/hasło/i), "password123");
    await user.click(screen.getByRole("button", { name: /zaloguj się/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("test@example.com", "password123");
    });
  });

  it("snapshot", () => {
    const { container } = renderLoginPage();
    expect(container).toMatchSnapshot();
  });
});
