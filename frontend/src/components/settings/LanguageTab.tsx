import { t, getLocale, setLocale } from "@/lib/i18n";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type Locale = "pl" | "en";

const LANGUAGES: { locale: Locale; flag: string; labelKey: "settings.language_tab.option_pl" | "settings.language_tab.option_en" }[] = [
  { locale: "pl", flag: "🇵🇱", labelKey: "settings.language_tab.option_pl" },
  { locale: "en", flag: "🇬🇧", labelKey: "settings.language_tab.option_en" },
];

export function LanguageTab() {
  const current = getLocale();

  function handleSelect(locale: Locale) {
    if (locale === current) return;
    setLocale(locale);
    window.location.reload();
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.language_tab.card_title")}</CardTitle>
          <CardDescription>{t("settings.language_tab.card_description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row gap-3">
            {LANGUAGES.map(({ locale, flag, labelKey }) => (
              <Button
                key={locale}
                variant={current === locale ? "default" : "outline"}
                className="justify-start gap-2 sm:w-40"
                onClick={() => handleSelect(locale)}
              >
                <span aria-hidden="true">{flag}</span>
                {t(labelKey)}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
