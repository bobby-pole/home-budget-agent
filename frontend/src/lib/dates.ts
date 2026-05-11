import { format } from "date-fns";
import { pl, enUS } from "date-fns/locale";
import { getLocale } from "@/lib/i18n";

const DATE_FNS_LOCALES = { pl, en: enUS };
const INTL_LOCALES = { pl: "pl-PL", en: "en-GB" };

export function getIntlLocale(): string {
  return INTL_LOCALES[getLocale()];
}

export function formatDate(date: Date | string, fmt: string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return format(d, fmt, { locale: DATE_FNS_LOCALES[getLocale()] });
}
