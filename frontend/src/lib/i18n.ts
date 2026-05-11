import pl from "@/locales/pl.json";
import en from "@/locales/en.json";

type Locale = "pl" | "en";

const locales = { pl, en } as const;

const LOCALE_STORAGE_KEY = "app_locale";

function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "pl";
  // localStorage has priority over browser language
  const stored = localStorage.getItem(LOCALE_STORAGE_KEY) as Locale | null;
  if (stored === "pl" || stored === "en") return stored;
  const lang = navigator.language?.split("-")[0];
  return lang === "en" ? "en" : "pl";
}

let currentLocale: Locale = detectLocale();

export function setLocale(locale: Locale): void {
  localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  currentLocale = locale;
}

export function getLocale(): Locale {
  return currentLocale;
}

export function t(key: string, params?: Record<string, string | number>): string {
  const keys = key.split(".");
  let current: unknown = locales[currentLocale];
  for (const k of keys) {
    if (typeof current !== "object" || current === null) return key;
    current = (current as Record<string, unknown>)[k];
  }
  let str: string;
  if (typeof current === "string") {
    str = current;
  } else {
    // fallback to Polish if key missing in current locale
    let fallback: unknown = locales["pl"];
    for (const k of keys) {
      if (typeof fallback !== "object" || fallback === null) return key;
      fallback = (fallback as Record<string, unknown>)[k];
    }
    str = typeof fallback === "string" ? fallback : key;
  }
  if (!params) return str;
  return str.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? `{${k}}`));
}
