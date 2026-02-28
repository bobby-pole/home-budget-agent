import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { RegisterPage } from "@/pages/RegisterPage";

const mockRegister = vi.fn();
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

function renderRegisterPage() {
  return render(
    <MemoryRouter>
      <RegisterPage />
    </MemoryRouter>
  );
}

describe("RegisterPage", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ token: null, register: mockRegister });
  });

  it("renders email, password and confirm password inputs", () => {
    renderRegisterPage();
    expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^hasło$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/potwierdź hasło/i)).toBeInTheDocument();
  });

  it("renders submit button with correct label", () => {
    renderRegisterPage();
    expect(screen.getByRole("button", { name: /zarejestruj się/i })).toBeInTheDocument();
  });

  it("renders link to login page", () => {
    renderRegisterPage();
    expect(screen.getByRole("link", { name: /zaloguj się/i })).toBeInTheDocument();
  });

  it("shows validation error when password is too short", async () => {
    const user = userEvent.setup();
    renderRegisterPage();

    await user.type(screen.getByLabelText(/^email$/i), "test@example.com");
    await user.type(screen.getByLabelText(/^hasło$/i), "short");
    await user.type(screen.getByLabelText(/potwierdź hasło/i), "short");
    await user.click(screen.getByRole("button", { name: /zarejestruj się/i }));

    await waitFor(() => {
      expect(screen.getByText(/minimum 8 znaków/i)).toBeInTheDocument();
    });
  });

  it("shows validation error when passwords do not match", async () => {
    const user = userEvent.setup();
    renderRegisterPage();

    await user.type(screen.getByLabelText(/^email$/i), "test@example.com");
    await user.type(screen.getByLabelText(/^hasło$/i), "password123");
    await user.type(screen.getByLabelText(/potwierdź hasło/i), "different456");
    await user.click(screen.getByRole("button", { name: /zarejestruj się/i }));

    await waitFor(() => {
      expect(screen.getByText(/hasła nie są zgodne/i)).toBeInTheDocument();
    });
  });

  it("shows validation error for invalid email format", async () => {
    renderRegisterPage();

    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "not-an-email" } });
    fireEvent.change(screen.getByLabelText(/^hasło$/i), { target: { value: "password123" } });
    fireEvent.change(screen.getByLabelText(/potwierdź hasło/i), { target: { value: "password123" } });
    fireEvent.submit(screen.getByRole("button", { name: /zarejestruj się/i }).closest("form")!);

    await waitFor(() => {
      expect(screen.getByText(/nieprawidłowy adres email/i)).toBeInTheDocument();
    });
  });

  it("already authenticated renders Navigate to /", () => {
    mockUseAuth.mockReturnValue({ token: "existing-token", register: mockRegister });
    renderRegisterPage();
    expect(screen.queryByRole("button", { name: /zarejestruj się/i })).not.toBeInTheDocument();
  });

  it("calls auth.register with email and password on submit", async () => {
    const user = userEvent.setup();
    mockRegister.mockResolvedValue(undefined);
    renderRegisterPage();

    await user.type(screen.getByLabelText(/^email$/i), "new@example.com");
    await user.type(screen.getByLabelText(/^hasło$/i), "password123");
    await user.type(screen.getByLabelText(/potwierdź hasło/i), "password123");
    await user.click(screen.getByRole("button", { name: /zarejestruj się/i }));

    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith("new@example.com", "password123");
    });
  });

  it("snapshot", () => {
    const { container } = renderRegisterPage();
    expect(container).toMatchSnapshot();
  });
});
