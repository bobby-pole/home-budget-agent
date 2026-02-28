import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "@/App";

vi.mock("@/components/AppSidebar", () => ({
  AppSidebar: () => <div data-testid="mock-sidebar">Sidebar</div>,
}));

vi.mock("@/components/BottomNav", () => ({
  BottomNav: () => <div data-testid="mock-bottom-nav">BottomNav</div>,
}));

vi.mock("@/components/DashboardHeader", () => ({
  DashboardHeader: () => <div data-testid="mock-header">Header</div>,
}));

vi.mock("@/pages/Dashboard", () => ({
  Dashboard: () => <div>Dashboard Page</div>,
}));

vi.mock("@/pages/LoginPage", () => ({
  LoginPage: () => <div>Login Page</div>,
}));

vi.mock("@/pages/RegisterPage", () => ({
  RegisterPage: () => <div>Register Page</div>,
}));

vi.mock("@/lib/ThemeProvider", () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("sonner", () => ({
  Toaster: () => null,
}));

const mockUseAuth = vi.fn();

vi.mock("@/context/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => mockUseAuth(),
}));

function navigate(path: string) {
  window.history.pushState({}, "", path);
}

describe("App", () => {
  beforeEach(() => {
    navigate("/");
  });

  it("renders without crashing", () => {
    mockUseAuth.mockReturnValue({ token: null });
    render(<App />);
  });

  it("unauthenticated user at / is redirected to Login Page", () => {
    mockUseAuth.mockReturnValue({ token: null });
    navigate("/");
    render(<App />);
    expect(screen.getByText("Login Page")).toBeInTheDocument();
  });

  it("authenticated user at / sees Dashboard Page", () => {
    mockUseAuth.mockReturnValue({ token: "mock-token" });
    navigate("/");
    render(<App />);
    expect(screen.getByText("Dashboard Page")).toBeInTheDocument();
  });

  it("/login renders Login Page regardless of auth state", () => {
    mockUseAuth.mockReturnValue({ token: null });
    navigate("/login");
    render(<App />);
    expect(screen.getByText("Login Page")).toBeInTheDocument();
  });

  it("/register renders Register Page regardless of auth state", () => {
    mockUseAuth.mockReturnValue({ token: null });
    navigate("/register");
    render(<App />);
    expect(screen.getByText("Register Page")).toBeInTheDocument();
  });

  it("catch-all /* redirects to / (then to Login if unauthenticated)", () => {
    mockUseAuth.mockReturnValue({ token: null });
    navigate("/some/unknown/path");
    render(<App />);
    expect(screen.getByText("Login Page")).toBeInTheDocument();
  });

  it("snapshot — unauthenticated state (shows login)", () => {
    mockUseAuth.mockReturnValue({ token: null });
    navigate("/");
    const { container } = render(<App />);
    expect(container).toMatchSnapshot();
  });

  it("snapshot — authenticated state (shows dashboard)", () => {
    mockUseAuth.mockReturnValue({ token: "mock-token" });
    navigate("/");
    const { container } = render(<App />);
    expect(container).toMatchSnapshot();
  });
});
