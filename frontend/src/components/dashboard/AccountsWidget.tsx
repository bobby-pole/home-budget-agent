import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Landmark,
  PiggyBank,
  Banknote,
  CreditCard,
  TrendingUp,
  ShieldAlert,
  Wallet,
  X,
  ExternalLink,
  Plus,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { AccountRead } from "@/client";
import { cn } from "@/lib/utils";
import { getIntlLocale } from "@/lib/dates";
import { t } from "@/lib/i18n";

interface AccountsWidgetProps {
  accounts: AccountRead[];
  selectedAccountId?: number | null;
  onSelectAccount?: (accountId: number) => void;
  onClearFilter?: () => void;
  isLoading?: boolean;
}

function getAccountIcon(type?: string) {
  switch (type) {
    case "savings":
      return <PiggyBank className="size-4 text-emerald-500" />;
    case "cash":
      return <Banknote className="size-4 text-amber-500" />;
    case "credit":
      return <CreditCard className="size-4 text-rose-500" />;
    case "tracking_asset":
      return <TrendingUp className="size-4 text-blue-500" />;
    case "tracking_liability":
      return <ShieldAlert className="size-4 text-destructive" />;
    case "checking":
    default:
      return <Landmark className="size-4 text-primary" />;
  }
}

function getAccountTypeLabel(type?: string): string {
  switch (type) {
    case "savings":
      return t("settings.accounts.form.types.savings");
    case "cash":
      return t("settings.accounts.form.types.cash");
    case "credit":
      return t("settings.accounts.form.types.credit");
    case "tracking_asset":
      return t("settings.accounts.form.types.tracking_asset");
    case "tracking_liability":
      return t("settings.accounts.form.types.tracking_liability");
    case "checking":
    default:
      return t("settings.accounts.form.types.checking");
  }
}

export function AccountsWidget({
  accounts = [],
  selectedAccountId,
  onSelectAccount,
  onClearFilter,
  isLoading,
}: AccountsWidgetProps) {
  const currency = accounts[0]?.currency ?? "PLN";

  // Net Worth Calculation
  // Assets: checking + savings + cash + tracking_asset
  // Liabilities: credit cards + tracking_liability
  const assetTypes = ["checking", "savings", "cash", "tracking_asset"];
  const liabilityTypes = ["credit", "tracking_liability"];

  const assets = accounts
    .filter((a) => assetTypes.includes(a.type ?? "checking"))
    .reduce((sum, a) => sum + (a.current_balance ?? 0), 0);

  const liabilities = accounts
    .filter((a) => liabilityTypes.includes(a.type ?? ""))
    .reduce((sum, a) => {
      const bal = a.current_balance ?? 0;
      return sum + (bal < 0 ? Math.abs(bal) : bal);
    }, 0);

  const netWorth = assets - liabilities;

  // Split accounts into On-Budget and Tracking
  const onBudgetAccounts = accounts.filter((a) => a.is_on_budget !== false);
  const trackingAccounts = accounts.filter((a) => a.is_on_budget === false);

  if (isLoading) {
    return (
      <Card className="rounded-[32px] border border-border/50 shadow-sm bg-card overflow-hidden animate-pulse h-[360px]" />
    );
  }

  return (
    <Card className="rounded-[32px] border border-border/50 shadow-sm bg-card overflow-hidden">
      {/* Header */}
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <div className="size-8 rounded-full bg-primary/10 text-primary flex items-center justify-center">
            <Wallet className="size-4" />
          </div>
          <CardTitle className="text-lg font-bold">
            {t("dashboard.accounts_widget.title")}
          </CardTitle>
        </div>
        <div className="flex items-center gap-1">
          {selectedAccountId && onClearFilter && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onClearFilter}
              className="h-7 px-2 text-xs font-semibold text-muted-foreground hover:text-foreground"
            >
              <X className="size-3 mr-1" />
              {t("dashboard.accounts_widget.clear_filter")}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            asChild
            className="h-8 px-2.5 text-xs font-bold text-primary hover:text-primary/80"
          >
            <Link to="/accounts">
              <ExternalLink className="size-3.5 mr-1" />
              {t("dashboard.accounts_widget.manage_accounts")}
            </Link>
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4 px-6 pb-6">
        {/* Net Worth Summary Banner */}
        <div className="rounded-2xl bg-muted/40 p-4 border border-border/40">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            {t("dashboard.accounts_widget.net_worth")}
          </div>
          <div className="flex items-baseline justify-between gap-2">
            <span
              className={cn(
                "text-2xl font-black tabular-nums tracking-tight",
                netWorth >= 0 ? "text-foreground" : "text-destructive"
              )}
            >
              {netWorth.toLocaleString(getIntlLocale(), {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}{" "}
              <span className="text-sm font-bold text-muted-foreground">{currency}</span>
            </span>
          </div>

          <div className="mt-3 pt-3 border-t border-border/40 grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-muted-foreground block font-medium">
                {t("dashboard.accounts_widget.total_assets")}
              </span>
              <span className="font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                +{assets.toLocaleString(getIntlLocale(), {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}{" "}
                {currency}
              </span>
            </div>
            <div className="text-right">
              <span className="text-muted-foreground block font-medium">
                {t("dashboard.accounts_widget.total_liabilities")}
              </span>
              <span className="font-bold tabular-nums text-rose-500">
                -{liabilities.toLocaleString(getIntlLocale(), {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}{" "}
                {currency}
              </span>
            </div>
          </div>
        </div>

        {/* Filter indicator banner if active */}
        {selectedAccountId && (
          <div className="flex items-center justify-between px-3 py-1.5 rounded-xl bg-primary/10 text-primary text-xs font-medium">
            <span>
              {t("dashboard.accounts_widget.filter_active")}{" "}
              <strong>
                {accounts.find((a) => a.id === selectedAccountId)?.name}
              </strong>
            </span>
            {onClearFilter && (
              <button
                type="button"
                onClick={onClearFilter}
                className="hover:underline font-bold"
              >
                {t("dashboard.accounts_widget.clear_filter")}
              </button>
            )}
          </div>
        )}

        {/* Accounts List */}
        {accounts.length === 0 ? (
          <div className="text-center py-6 px-4 space-y-3">
            <p className="text-sm text-muted-foreground">
              {t("dashboard.accounts_widget.no_accounts")}
            </p>
            <Button size="sm" variant="outline" asChild>
              <Link to="/accounts">
                <Plus className="size-4 mr-1.5" />
                {t("dashboard.accounts_widget.add_account")}
              </Link>
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            {/* On-Budget Group */}
            {onBudgetAccounts.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground px-1">
                  {t("dashboard.accounts_widget.on_budget_group")}
                </div>
                <div className="space-y-1.5">
                  {onBudgetAccounts.map((acc) => {
                    const isSelected = selectedAccountId === acc.id;
                    const isNegative = (acc.current_balance ?? 0) < 0;

                    return (
                      <button
                        key={acc.id}
                        type="button"
                        onClick={() => onSelectAccount?.(acc.id)}
                        className={cn(
                          "w-full text-left flex items-center justify-between p-2.5 rounded-xl border transition-all cursor-pointer",
                          "hover:bg-muted/60 active:scale-[0.99]",
                          isSelected
                            ? "border-primary bg-primary/5 shadow-xs ring-1 ring-primary"
                            : "border-border/40 bg-card hover:border-border/80"
                        )}
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1 pr-2">
                          <div className="size-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                            {getAccountIcon(acc.type)}
                          </div>
                          <div className="min-w-0 flex-1">
                            <span className="font-semibold text-sm truncate block">
                              {acc.name}
                            </span>
                            <span className="text-[11px] text-muted-foreground block truncate">
                              {getAccountTypeLabel(acc.type)}
                            </span>
                          </div>
                        </div>
                        <div className="text-right shrink-0">
                          <span
                            className={cn(
                              "font-bold text-sm tabular-nums",
                              isNegative ? "text-destructive" : "text-foreground"
                            )}
                          >
                            {(acc.current_balance ?? 0).toLocaleString(
                              getIntlLocale(),
                              {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                              }
                            )}
                          </span>
                          <span className="text-[10px] text-muted-foreground block font-medium">
                            {acc.currency}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Tracking Group */}
            {trackingAccounts.length > 0 && (
              <div className="space-y-1.5 pt-2 border-t border-border/30">
                <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground px-1">
                  {t("dashboard.accounts_widget.tracking_group")}
                </div>
                <div className="space-y-1.5">
                  {trackingAccounts.map((acc) => {
                    const isSelected = selectedAccountId === acc.id;
                    const isNegative = (acc.current_balance ?? 0) < 0;

                    return (
                      <button
                        key={acc.id}
                        type="button"
                        onClick={() => onSelectAccount?.(acc.id)}
                        className={cn(
                          "w-full text-left flex items-center justify-between p-2.5 rounded-xl border transition-all cursor-pointer",
                          "hover:bg-muted/60 active:scale-[0.99]",
                          isSelected
                            ? "border-primary bg-primary/5 shadow-xs ring-1 ring-primary"
                            : "border-border/40 bg-card hover:border-border/80"
                        )}
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1 pr-2">
                          <div className="size-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                            {getAccountIcon(acc.type)}
                          </div>
                          <div className="min-w-0 flex-1">
                            <span className="font-semibold text-sm truncate block">
                              {acc.name}
                            </span>
                            <span className="text-[11px] text-muted-foreground block truncate">
                              {getAccountTypeLabel(acc.type)}
                            </span>
                          </div>
                        </div>
                        <div className="text-right shrink-0">
                          <span
                            className={cn(
                              "font-bold text-sm tabular-nums",
                              isNegative ? "text-destructive" : "text-foreground"
                            )}
                          >
                            {(acc.current_balance ?? 0).toLocaleString(
                              getIntlLocale(),
                              {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                              }
                            )}
                          </span>
                          <span className="text-[10px] text-muted-foreground block font-medium">
                            {acc.currency}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
