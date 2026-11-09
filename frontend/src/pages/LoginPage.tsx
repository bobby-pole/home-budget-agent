// frontend/src/pages/LoginPage.tsx
import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Navigate, Link, useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, ShieldCheck, Globe } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { t, getLocale, setLocale, type Locale } from "@/lib/i18n";

const LANGUAGES: { locale: Locale; flag: string; labelKey: "demo.login.language_pl" | "demo.login.language_en" }[] = [
  { locale: "pl", flag: "🇵🇱", labelKey: "demo.login.language_pl" },
  { locale: "en", flag: "🇬🇧", labelKey: "demo.login.language_en" },
];

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
  const [currentLocale, setCurrentLocale] = useState<Locale>(getLocale());

  const handleLocaleChange = (newLocale: Locale) => {
    if (newLocale === currentLocale) return;
    setLocale(newLocale);
    setCurrentLocale(newLocale);
  };

  const { register, handleSubmit, setValue, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const handleDemoLogin = async () => {
    try {
      setIsDemoLoading(true);
      await loginDemo(undefined, currentLocale);
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
      void loginDemo(undefined, currentLocale)
        .then(() => {
          navigate("/");
        })
        .catch((err: unknown) => {
          const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          toast.error(msg || t("demo.login.error_login"));
          setIsDemoLoading(false);
        });
    }
  }, [isAutoDemo, token, loginDemo, navigate, currentLocale]);

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
            <div className="flex justify-between items-center mb-3">
              <div className="inline-flex items-center gap-1.5 text-xs text-muted-foreground font-medium">
                <Globe className="h-3.5 w-3.5" />
                <span>{t("demo.login.language_label")}</span>
              </div>
              <div className="inline-flex items-center rounded-lg border border-border/60 bg-muted/40 p-0.5">
                {LANGUAGES.map(({ locale, flag, labelKey }) => (
                  <Button
                    key={locale}
                    type="button"
                    variant={currentLocale === locale ? "default" : "ghost"}
                    size="sm"
                    className="h-7 px-2.5 text-xs font-medium gap-1.5"
                    onClick={() => handleLocaleChange(locale)}
                  >
                    <span aria-hidden="true">{flag}</span>
                    <span>{t(labelKey)}</span>
                  </Button>
                ))}
              </div>
            </div>
            <CardTitle className="text-2xl font-bold tracking-tight">
              {t("demo.login.title")}
            </CardTitle>
            <CardDescription className="text-sm mt-1.5 text-muted-foreground leading-relaxed">
              {t("demo.login.description")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <div className="rounded-xl border border-border/60 bg-muted/30 p-4 text-xs text-muted-foreground space-y-1.5">
              <div className="font-semibold text-foreground flex items-center gap-1.5">
                <ShieldCheck className="h-4 w-4 text-primary" />
                {t("demo.login.privacy_notice_title")}
              </div>
              <p className="leading-relaxed">
                {t("demo.login.privacy_notice_body")}
              </p>
            </div>

            <Button
              type="button"
              size="lg"
              className="w-full font-medium h-11 text-sm sm:text-base"
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
