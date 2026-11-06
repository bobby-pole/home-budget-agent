// frontend/src/pages/LoginPage.tsx
import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Navigate, Link, useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { t } from "@/lib/i18n";

const schema = z.object({
  email: z.email(t("auth.login.validation.email_invalid")),
  password: z.string().min(1, t("auth.login.validation.password_required")),
});

type FormData = z.infer<typeof schema>;

export function LoginPage() {
  const { token, login, loginDemo } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  const isDemoMode = import.meta.env.VITE_DEMO_MODE === "true";
  const isAutoDemo = searchParams.get("demo") === "true" || location.pathname === "/demo";
  const [isDemoLoading, setIsDemoLoading] = useState(isAutoDemo);
  const [showTraditional, setShowTraditional] = useState(!isDemoMode);

  const { register, handleSubmit, setValue, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const handleDemoLogin = async () => {
    try {
      setIsDemoLoading(true);
      await loginDemo();
      navigate("/");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || t("demo.login.error_login"));
    } finally {
      setIsDemoLoading(false);
    }
  };

  useEffect(() => {
    if (isAutoDemo && !token) {
      void loginDemo()
        .then(() => {
          navigate("/");
        })
        .catch((err: unknown) => {
          const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          toast.error(msg || t("demo.login.error_login"));
          setIsDemoLoading(false);
        });
    }
  }, [isAutoDemo, token, loginDemo, navigate]);

  if (token) return <Navigate to="/" replace />;

  const onSubmit = async (data: FormData) => {
    try {
      await login(data.email, data.password);
      navigate("/");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || t("auth.login.error_default"));
    }
  };

  const handleFillTestData = () => {
    setValue("email", "test@example.com");
    setValue("password", "password123");
  };

  if (isDemoMode) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4 py-8">
        <Card className="w-full max-w-md border-border shadow-lg">
          <CardHeader className="text-center pb-2">
            <CardTitle className="text-2xl font-bold tracking-tight">
              {t("demo.login.title")}
            </CardTitle>
            <CardDescription className="text-sm mt-1.5 text-muted-foreground">
              {t("demo.login.description")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <Button
              type="button"
              size="lg"
              className="w-full font-medium h-11"
              onClick={handleDemoLogin}
              disabled={isDemoLoading}
            >
              {isDemoLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("demo.login.loading")}
                </>
              ) : (
                t("demo.login.button")
              )}
            </Button>

            <div className="pt-1 text-center">
              <button
                type="button"
                onClick={() => setShowTraditional((prev) => !prev)}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors underline underline-offset-4"
              >
                {showTraditional ? t("demo.login.hide_traditional") : t("demo.login.show_traditional")}
              </button>
            </div>

            {showTraditional && (
              <div className="pt-4 border-t border-border">
                <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                  <div className="space-y-1">
                    <Label htmlFor="email">{t("profile.email")}</Label>
                    <Input
                      id="email"
                      type="email"
                      placeholder="jan@example.com"
                      {...register("email")}
                    />
                    {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
                  </div>

                  <div className="space-y-1">
                    <Label htmlFor="password">{t("auth.login.password_label")}</Label>
                    <Input
                      id="password"
                      type="password"
                      placeholder="••••••••"
                      {...register("password")}
                    />
                    {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
                  </div>

                  <div className="space-y-2 pt-2">
                    <Button type="submit" className="w-full" disabled={isSubmitting}>
                      {isSubmitting ? t("auth.login.submit_pending") : t("auth.login.submit_idle")}
                    </Button>
                  </div>
                </form>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">{t("auth.login.title")}</CardTitle>
          <CardDescription>{t("auth.login.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="email">{t("profile.email")}</Label>
              <Input
                id="email"
                type="email"
                placeholder="jan@example.com"
                {...register("email")}
              />
              {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
            </div>

            <div className="space-y-1">
              <Label htmlFor="password">{t("auth.login.password_label")}</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                {...register("password")}
              />
              {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
            </div>

            <div className="space-y-2 pt-2">
              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? t("auth.login.submit_pending") : t("auth.login.submit_idle")}
              </Button>

              {import.meta.env.DEV && (
                <Button
                  type="button"
                  variant="secondary"
                  className="w-full text-xs"
                  onClick={handleFillTestData}
                >
                  {t("auth.login.test_data")}
                </Button>
              )}
            </div>
          </form>

          <p className="mt-4 text-center text-sm text-muted-foreground">
            {t("auth.login.no_account")}{" "}
            <Link to="/register" className="underline underline-offset-4 hover:text-primary">
              {t("auth.login.register_link")}
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
