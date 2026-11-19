import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import type {
  AccountRead,
  AutoMergePolicy,
  ConnectionOAuthStartResponse,
  ConnectionSettingsUpdate,
  ExternalReceiptConnectionCreate,
  ExternalReceiptConnectionRead,
} from "@/client";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Store, RefreshCw, Unplug, Plus, ShieldCheck, AlertTriangle, Clock, ExternalLink, KeyRound, Pause, Play } from "lucide-react";

const STORES = [
  { id: "lidl", name: "Lidl Plus", icon: "/brands/lidl.svg" },
  { id: "biedronka", name: "Biedronka", icon: "/brands/biedronka.ico" },
];

function getCurrentMonthStartDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}-01`;
}

function ConnectionImportPreferences({
  conn,
  accounts,
  isSaving,
  onSave,
}: {
  conn: ExternalReceiptConnectionRead;
  accounts: AccountRead[];
  isSaving: boolean;
  onSave: (id: number, settings: ConnectionSettingsUpdate) => void;
}) {
  const activeAccounts = accounts.filter((a) => a.is_active !== false);
  const currentMonthStart = getCurrentMonthStartDate();

  const [accountVal, setAccountVal] = useState<string>(
    conn.default_account_id
      ? String(conn.default_account_id)
      : conn.suggested_account_id
        ? String(conn.suggested_account_id)
        : "none"
  );
  const [mergePolicy, setMergePolicy] = useState<AutoMergePolicy>(
    conn.auto_merge_policy ?? "auto"
  );
  const [syncFromDate, setSyncFromDate] = useState<string>(
    conn.sync_from_date ? String(conn.sync_from_date).slice(0, 10) : currentMonthStart
  );

  const handleSubmit = () => {
    onSave(conn.id, {
      default_account_id: accountVal === "none" ? null : parseInt(accountVal, 10),
      auto_merge_policy: mergePolicy,
      sync_from_date: syncFromDate.trim() ? syncFromDate.trim() : null,
    });
  };

  return (
    <div className="rounded-lg border bg-muted/20 p-3 space-y-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-foreground">
          {t("settings.connections.preferences.title")}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="space-y-1">
          <Label htmlFor={`conn-acc-${conn.id}`} className="text-xs">
            {t("settings.connections.preferences.default_account_label")}
          </Label>
          <Select value={accountVal} onValueChange={setAccountVal}>
            <SelectTrigger id={`conn-acc-${conn.id}`} className="h-8 text-xs">
              <SelectValue placeholder={t("settings.connections.preferences.default_account_placeholder")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{t("settings.connections.preferences.account_none")}</SelectItem>
              {activeAccounts.map((acc) => (
                <SelectItem key={acc.id} value={String(acc.id)}>
                  {acc.name}
                  {conn.suggested_account_id === acc.id
                    ? ` (${t("settings.connections.preferences.suggested_badge")})`
                    : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label htmlFor={`conn-merge-${conn.id}`} className="text-xs">
            {t("settings.connections.preferences.merge_policy_label")}
          </Label>
          <Select value={mergePolicy} onValueChange={(v) => setMergePolicy(v as AutoMergePolicy)}>
            <SelectTrigger id={`conn-merge-${conn.id}`} className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">{t("settings.connections.preferences.merge_auto")}</SelectItem>
              <SelectItem value="manual">{t("settings.connections.preferences.merge_manual")}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label htmlFor={`conn-date-${conn.id}`} className="text-xs">
            {t("settings.connections.preferences.sync_from_label")}
          </Label>
          <Input
            id={`conn-date-${conn.id}`}
            type="date"
            value={syncFromDate}
            onChange={(e) => setSyncFromDate(e.target.value)}
            className="h-8 text-xs"
          />
          <div className="flex flex-wrap gap-1 pt-0.5">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-[11px]"
              onClick={() => setSyncFromDate(currentMonthStart)}
            >
              {t("settings.connections.preferences.preset_current_month")}
            </Button>
            {conn.budget_first_month_date && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[11px]"
                onClick={() => setSyncFromDate(String(conn.budget_first_month_date).slice(0, 10))}
              >
                {t("settings.connections.preferences.preset_budget_start")}
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={isSaving}
          onClick={handleSubmit}
          className="h-7 text-xs"
        >
          {isSaving
            ? t("settings.connections.preferences.saving_button")
            : t("settings.connections.preferences.save_button")}
        </Button>
      </div>
    </div>
  );
}

export function ConnectionsTab() {
  const queryClient = useQueryClient();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [formData, setFormData] = useState<ExternalReceiptConnectionCreate>({
    provider: "lidl",
  });
  const [oauthSession, setOauthSession] = useState<ConnectionOAuthStartResponse | null>(null);
  const [desktopOAuthConnectionId, setDesktopOAuthConnectionId] = useState<number | null>(null);
  const [callbackInput, setCallbackInput] = useState("");

  const hasConfigEndpoint = typeof api.getAppConfig === "function";
  const { data: appConfig, isLoading: isConfigLoading } = useQuery({
    queryKey: ["app-config"],
    queryFn: async () => (hasConfigEndpoint ? api.getAppConfig() : null),
    enabled: hasConfigEndpoint,
    staleTime: 60_000,
  });

  const isTrustedLocal = !hasConfigEndpoint
    ? true
    : Boolean(!isConfigLoading && appConfig?.trusted_local);
  const showCentralVpsNotice = Boolean(hasConfigEndpoint && !isConfigLoading && appConfig && !appConfig.trusted_local);
  const lidlConnectorEnabled = !hasConfigEndpoint
    ? true
    : Boolean(!isConfigLoading && (appConfig?.lidl_connector_enabled ?? true));
  const showLidlDisabledNotice = Boolean(
    hasConfigEndpoint && !isConfigLoading && appConfig && appConfig.lidl_connector_enabled === false
  );
  const isDesktopOAuthAvailable = Boolean(
    isTrustedLocal && lidlConnectorEnabled && appConfig?.desktop_oauth_available
  );

  const { data: connections = [], isLoading } = useQuery({
    queryKey: ["connections"],
    queryFn: api.getConnections,
  });

  const hasAccountsEndpoint = typeof api.getAccounts === "function";
  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: async () => (hasAccountsEndpoint ? api.getAccounts() : []),
    enabled: hasAccountsEndpoint,
  });

  const hasSettingsEndpoint = typeof api.updateConnectionSettings === "function";

  const updateSettingsMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: ConnectionSettingsUpdate }) =>
      api.updateConnectionSettings(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast.success(t("settings.connections.preferences.toast_saved"));
    },
    onError: () => toast.error(t("common.error")),
  });

  const providerAlreadyAdded = connections.some((connection) => connection.provider === formData.provider);

  const createMutation = useMutation({
    mutationFn: (data: ExternalReceiptConnectionCreate) => api.createConnection(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      setIsDialogOpen(false);
      setFormData({
        provider: "lidl",
      });
      toast.info(t("settings.connections.toast_authorization_required"));
    },
    onError: () => toast.error(t("common.error")),
  });

  const startOAuthMutation = useMutation({
    mutationFn: (id: number) => api.startConnectionOAuth(id),
    onSuccess: (data) => {
      setDesktopOAuthConnectionId(null);
      setOauthSession(data);
      setCallbackInput("");
    },
    onError: () => toast.error(t("common.error")),
  });

  const completeOAuthMutation = useMutation({
    mutationFn: ({ id, callback }: { id: number; callback: string }) =>
      api.completeConnectionOAuth(id, { callback_url_or_code: callback }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      setOauthSession(null);
      setDesktopOAuthConnectionId(null);
      setCallbackInput("");
      toast.success(t("settings.connections.toast_oauth_success"));
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast.error(t("settings.connections.toast_oauth_error"));
    },
  });

  const desktopOAuthMutation = useMutation({
    mutationFn: (id: number) => api.desktopLoginConnectionOAuth(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      setOauthSession(null);
      setDesktopOAuthConnectionId(null);
      setCallbackInput("");
      toast.success(t("settings.connections.toast_oauth_success"));
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast.error(t("settings.connections.toast_oauth_error"));
    },
  });

  const syncNowMutation = useMutation({
    mutationFn: (id: number) => api.syncNowConnection(id),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["budget-summary"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
      toast.success(res.message || t("settings.connections.toast_sync_queued"));
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast.error(t("common.error"));
    },
  });

  const reconnectMutation = useMutation({
    mutationFn: (id: number) => api.reconnectConnection(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast.info(t("settings.connections.toast_reconnect_prompt"));
    },
    onError: () => toast.error(t("common.error")),
  });

  const disconnectMutation = useMutation({
    mutationFn: (id: number) => api.disconnectConnection(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast.success(t("settings.connections.toast_disconnected"));
    },
    onError: () => toast.error(t("common.error")),
  });

  const toggleEnabledMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.setConnectionEnabled(id, { enabled }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast.success(
        variables.enabled
          ? t("settings.connections.toast_resumed")
          : t("settings.connections.toast_paused")
      );
    },
    onError: () => toast.error(t("common.error")),
  });

  const getErrorReasonText = (code?: string | null): string | null => {
    switch (code) {
      case "AUTH_EXPIRED":
        return t("settings.connections.error_reasons.AUTH_EXPIRED");
      case "REAUTH_REQUIRED":
        return t("settings.connections.error_reasons.REAUTH_REQUIRED");
      case "MFA_REQUIRED":
        return t("settings.connections.error_reasons.MFA_REQUIRED");
      case "RATE_LIMITED":
        return t("settings.connections.error_reasons.RATE_LIMITED");
      case "NETWORK_ERROR":
        return t("settings.connections.error_reasons.NETWORK_ERROR");
      case "PROVIDER_UNAVAILABLE":
        return t("settings.connections.error_reasons.PROVIDER_UNAVAILABLE");
      case "PROVIDER_SCHEMA_CHANGED":
        return t("settings.connections.error_reasons.PROVIDER_SCHEMA_CHANGED");
      case "PROVIDER_REVOCATION_UNAVAILABLE":
        return t("settings.connections.error_reasons.PROVIDER_REVOCATION_UNAVAILABLE");
      case "ENCRYPTION_KEY_MISSING":
        return t("settings.connections.error_reasons.ENCRYPTION_KEY_MISSING");
      case "TOKEN_DECRYPTION_FAILED":
        return t("settings.connections.error_reasons.TOKEN_DECRYPTION_FAILED");
      case "CONNECTOR_DISABLED":
        return t("settings.connections.error_reasons.CONNECTOR_DISABLED");
      case "SYNC_FAILED":
        return t("settings.connections.error_reasons.SYNC_FAILED");
      default:
        return null;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return <Badge variant="default" className="bg-emerald-600 hover:bg-emerald-700">{t("settings.connections.status_active")}</Badge>;
      case "expired":
        return <Badge variant="secondary" className="bg-amber-500 text-white">{t("settings.connections.status_expired")}</Badge>;
      case "reauth_required":
        return <Badge variant="destructive">{t("settings.connections.status_reauth_required")}</Badge>;
      case "sync_error":
        return <Badge variant="destructive">{t("settings.connections.status_sync_error")}</Badge>;
      case "disconnected":
      default:
        return <Badge variant="outline">{t("settings.connections.status_disconnected")}</Badge>;
    }
  };

  const formatDateTime = (isoString?: string | null) => {
    if (!isoString) return "-";
    try {
      return new Date(isoString).toLocaleString();
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h3 className="text-xl font-semibold tracking-tight">{t("settings.connections.section_title")}</h3>
          <p className="text-sm text-muted-foreground">
            {t("settings.connections.section_description")}
          </p>
        </div>

        <Dialog open={isDialogOpen} onOpenChange={(open) => {
          if (open) {
            setFormData({ provider: STORES.find((store) => !connections.some((connection) => connection.provider === store.id))?.id ?? "lidl" });
          }
          setIsDialogOpen(open);
        }}>
          <DialogTrigger asChild>
            <Button className="gap-2 shrink-0">
              <Plus className="size-4" />
              {t("settings.connections.add_button")}
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[480px]">
            <DialogHeader>
              <DialogTitle>{t("settings.connections.connect_modal_title")}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">{t("settings.connections.connect_modal_provider")}</legend>
                <div className="grid grid-cols-2 gap-3">
                  {STORES.map((store) => {
                    const added = connections.some((connection) => connection.provider === store.id);
                    return (
                      <label key={store.id} className={`relative flex cursor-pointer flex-col items-center gap-3 rounded-xl border p-4 text-center has-[:checked]:border-primary has-[:checked]:bg-primary/5 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring ${added ? "cursor-not-allowed opacity-50" : "hover:bg-muted/50"}`}>
                        <input
                          type="radio"
                          name="store-provider"
                          value={store.id}
                          checked={formData.provider === store.id}
                          onChange={() => setFormData({ provider: store.id })}
                          disabled={added || createMutation.isPending}
                          className="absolute right-3 top-3 accent-primary"
                        />
                        <img src={store.icon} alt="" className="size-12 rounded-md object-contain" />
                        <span className="text-sm font-medium">{store.name}</span>
                        {added && <span className="text-xs text-muted-foreground">{t("settings.connections.already_added")}</span>}
                      </label>
                    );
                  })}
                </div>
              </fieldset>

              <div className="p-3 bg-muted/60 rounded-lg text-xs text-muted-foreground flex gap-2">
                <ShieldCheck className="size-4 shrink-0 text-emerald-600 mt-0.5" />
                <span>{t("settings.connections.connect_modal_authorization_note")}</span>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
                {t("settings.connections.connect_modal_cancel")}
              </Button>
              <Button
                disabled={providerAlreadyAdded || createMutation.isPending}
                onClick={() => createMutation.mutate(formData)}
              >
                {t("settings.connections.connect_modal_save")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Experimental Disclaimer Alert */}
      <Card className="border-amber-500/30 bg-amber-50/50 dark:bg-amber-950/10">
        <CardContent className="pt-4 pb-4 flex gap-3 text-xs text-muted-foreground">
          <AlertTriangle className="size-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-medium text-foreground flex items-center gap-2">
              <span>{t("settings.connections.section_title")}</span>
              <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-500/40">
                {t("settings.connections.experimental_badge")}
              </Badge>
            </div>
            <p>{t("settings.connections.disclaimer")}</p>
          </div>
        </CardContent>
      </Card>

      {/* Privacy Boundary Notice when running on Central VPS / Demo */}
      {showCentralVpsNotice && (
        <Card className="border-sky-500/30 bg-sky-50/50 dark:bg-sky-950/10">
          <CardContent className="pt-4 pb-4 flex gap-3 text-xs text-muted-foreground">
            <ShieldCheck className="size-5 text-sky-600 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <div className="font-medium text-foreground">
                {t("settings.connections.trusted_local_required_title")}
              </div>
              <p>{t("settings.connections.trusted_local_required_desc")}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Independent Lidl Connector Disabled Notice */}
      {showLidlDisabledNotice && (
        <Card className="border-amber-500/40 bg-amber-50/50 dark:bg-amber-950/10">
          <CardContent className="pt-4 pb-4 flex gap-3 text-xs text-muted-foreground">
            <AlertTriangle className="size-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <div className="font-medium text-foreground">
                {t("settings.connections.lidl_disabled_title")}
              </div>
              <p>{t("settings.connections.lidl_disabled_desc")}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="py-8 text-center text-sm text-muted-foreground">
          {t("common.loading")}
        </div>
      ) : connections.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="py-12 text-center space-y-3">
            <div className="size-12 rounded-full bg-muted flex items-center justify-center mx-auto text-muted-foreground">
              <Store className="size-6" />
            </div>
            <div className="space-y-1">
              <h4 className="font-medium text-base">{t("settings.connections.empty_title")}</h4>
              <p className="text-sm text-muted-foreground max-w-sm mx-auto">
                {t("settings.connections.empty_desc")}
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {connections.map((conn: ExternalReceiptConnectionRead) => (
            <Card key={conn.id} className="overflow-hidden">
              <CardHeader className="pb-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-3">
                    {STORES.find((store) => store.id === conn.provider) ? (
                      <img src={STORES.find((store) => store.id === conn.provider)!.icon} alt="" className="size-10 rounded-lg object-contain" />
                    ) : (
                      <Store aria-hidden="true" className="size-9 text-muted-foreground" />
                    )}
                    <div>
                      <CardTitle className="text-base flex items-center gap-2">
                        <span>{STORES.find((store) => store.id === conn.provider)?.name ?? conn.provider}</span>
                      </CardTitle>
                      <CardDescription className="text-xs">
                        {t("settings.connections.sync_frequency")}: {t("settings.connections.sync_frequency_val")}
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {conn.is_enabled === false && (
                      <Badge variant="secondary">{t("settings.connections.status_paused")}</Badge>
                    )}
                    {getStatusBadge(conn.status)}
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4 pt-0">
                {/* Data Scope & Health Info */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs bg-muted/40 p-3 rounded-lg">
                  <div className="space-y-1">
                    <span className="text-muted-foreground font-medium">{t("settings.connections.data_scope_title")}:</span>
                    <p className="text-muted-foreground leading-relaxed">{t("settings.connections.data_scope_desc")}</p>
                  </div>
                  <div className="space-y-1.5 border-t md:border-t-0 md:border-l border-border/50 pt-2 md:pt-0 md:pl-3">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">{t("settings.connections.last_success")}:</span>
                      <span className="font-medium">{formatDateTime(conn.last_success_at)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">{t("settings.connections.next_sync")}:</span>
                      <span className="font-medium">{formatDateTime(conn.next_sync_at)}</span>
                    </div>
                    {conn.sync_requested_at && (
                      <div className="flex items-center gap-1.5 text-amber-600 font-medium">
                        <Clock className="size-3.5" />
                        <span>{t("settings.connections.toast_sync_queued")}</span>
                      </div>
                    )}
                    {conn.last_error_code && (
                      <div className="space-y-1 pt-1">
                        <div className="flex justify-between text-destructive">
                          <span>{t("settings.connections.status_sync_error")}:</span>
                          <span className="font-mono text-[11px]">{conn.last_error_code}</span>
                        </div>
                        {getErrorReasonText(conn.last_error_code) && (
                          <p className="text-[11px] text-destructive/90 leading-snug">
                            {getErrorReasonText(conn.last_error_code)}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {!conn.has_token && conn.status === "reauth_required" && !conn.last_error_code && (
                  <p className="text-sm text-muted-foreground">{t("settings.connections.authorization_unavailable")}</p>
                )}

                {hasSettingsEndpoint && conn.status !== "disconnected" && (
                  <ConnectionImportPreferences
                    key={`${conn.id}-${conn.updated_at}`}
                    conn={conn}
                    accounts={accounts}
                    isSaving={updateSettingsMutation.isPending}
                    onSave={(id, settingsData) =>
                      updateSettingsMutation.mutate({ id, data: settingsData })
                    }
                  />
                )}

                {/* Actions */}
                <div className="flex flex-wrap items-center justify-end gap-2 pt-1 border-t">
                  {conn.provider === "lidl" && conn.status !== "active" && (
                    <Button
                      size="sm"
                      variant="default"
                      disabled={
                        !isTrustedLocal ||
                        !lidlConnectorEnabled ||
                        startOAuthMutation.isPending ||
                        desktopOAuthMutation.isPending
                      }
                      onClick={() => {
                        if (isDesktopOAuthAvailable) {
                          setOauthSession(null);
                          setCallbackInput("");
                          setDesktopOAuthConnectionId(conn.id);
                        } else {
                          startOAuthMutation.mutate(conn.id);
                        }
                      }}
                      className="gap-1.5"
                    >
                      <KeyRound className="size-3.5" />
                      {t("settings.connections.authorize_lidl_btn")}
                    </Button>
                  )}

                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      !isTrustedLocal ||
                      conn.is_enabled === false ||
                      (conn.provider === "lidl" && !lidlConnectorEnabled) ||
                      (conn.status !== "active" && conn.status !== "sync_error") ||
                      !conn.has_token ||
                      syncNowMutation.isPending
                    }
                    onClick={() => syncNowMutation.mutate(conn.id)}
                    className="gap-1.5"
                  >
                    <RefreshCw className={`size-3.5 ${syncNowMutation.isPending ? "animate-spin" : ""}`} />
                    {syncNowMutation.isPending
                      ? t("settings.connections.syncing_btn")
                      : t("settings.connections.sync_now_btn")}
                  </Button>

                  {conn.status !== "disconnected" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={toggleEnabledMutation.isPending}
                      onClick={() =>
                        toggleEnabledMutation.mutate({
                          id: conn.id,
                          enabled: conn.is_enabled === false,
                        })
                      }
                      className="gap-1.5"
                    >
                      {conn.is_enabled === false ? (
                        <>
                          <Play className="size-3.5" />
                          {t("settings.connections.resume_btn")}
                        </>
                      ) : (
                        <>
                          <Pause className="size-3.5" />
                          {t("settings.connections.pause_btn")}
                        </>
                      )}
                    </Button>
                  )}

                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => reconnectMutation.mutate(conn.id)}
                  >
                    {t("settings.connections.reconnect_btn")}
                  </Button>

                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive hover:bg-destructive/10 gap-1.5">
                        <Unplug className="size-3.5" />
                        {t("settings.connections.disconnect_btn")}
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>{t("settings.connections.disconnect_dialog_title")}</AlertDialogTitle>
                        <AlertDialogDescription>
                          {t("settings.connections.disconnect_dialog_desc")}
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>{t("settings.connections.disconnect_dialog_cancel")}</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => disconnectMutation.mutate(conn.id)}
                          className="bg-destructive hover:bg-destructive/90 text-destructive-foreground"
                        >
                          {t("settings.connections.disconnect_dialog_confirm")}
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Lidl Plus OAuth2 PKCE Modal */}
      <Dialog
        open={Boolean(oauthSession) || desktopOAuthConnectionId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setOauthSession(null);
            setDesktopOAuthConnectionId(null);
            setCallbackInput("");
          }
        }}
      >
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>{t("settings.connections.oauth_modal_title")}</DialogTitle>
          </DialogHeader>
          {desktopOAuthConnectionId !== null && !oauthSession && (
            <div className="space-y-4 py-2">
              <p className="text-sm text-muted-foreground">
                {t("settings.connections.oauth_desktop_desc")}
              </p>
              <div className="flex flex-col gap-2">
                <Button
                  type="button"
                  disabled={desktopOAuthMutation.isPending}
                  onClick={() => desktopOAuthMutation.mutate(desktopOAuthConnectionId)}
                  className="gap-2"
                >
                  <KeyRound className="size-4" />
                  {desktopOAuthMutation.isPending
                    ? t("settings.connections.oauth_desktop_logging_in_btn")
                    : t("settings.connections.oauth_desktop_login_btn")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={desktopOAuthMutation.isPending || startOAuthMutation.isPending}
                  onClick={() => startOAuthMutation.mutate(desktopOAuthConnectionId)}
                >
                  {t("settings.connections.oauth_manual_fallback_btn")}
                </Button>
              </div>
              <div className="flex justify-end pt-1">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setDesktopOAuthConnectionId(null);
                    setCallbackInput("");
                  }}
                >
                  {t("settings.connections.connect_modal_cancel")}
                </Button>
              </div>
            </div>
          )}
          {oauthSession && (
            <div className="space-y-4 py-2">
              {!isDesktopOAuthAvailable && (
                <p className="text-xs text-muted-foreground bg-muted/60 rounded-md p-2.5">
                  {t("settings.connections.oauth_desktop_unavailable_hint")}
                </p>
              )}
              <div className="space-y-2 text-sm">
                <p className="text-muted-foreground">{t("settings.connections.oauth_step1_desc")}</p>
                <Button
                  asChild
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                >
                  <a href={oauthSession.authorize_url} target="_blank" rel="noreferrer">
                    <ExternalLink className="size-3.5" />
                    {t("settings.connections.oauth_open_login_btn")}
                  </a>
                </Button>
              </div>

              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">{t("settings.connections.oauth_step2_desc")}</p>
                <Label htmlFor="oauth-callback-input">{t("settings.connections.oauth_callback_label")}</Label>
                <Input
                  id="oauth-callback-input"
                  value={callbackInput}
                  onChange={(e) => setCallbackInput(e.target.value)}
                  placeholder={t("settings.connections.oauth_callback_placeholder")}
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setOauthSession(null);
                    setDesktopOAuthConnectionId(null);
                    setCallbackInput("");
                  }}
                >
                  {t("settings.connections.connect_modal_cancel")}
                </Button>
                <Button
                  type="button"
                  disabled={!callbackInput.trim() || completeOAuthMutation.isPending}
                  onClick={() =>
                    completeOAuthMutation.mutate({
                      id: oauthSession.connection_id,
                      callback: callbackInput.trim(),
                    })
                  }
                >
                  {completeOAuthMutation.isPending
                    ? t("settings.connections.oauth_submitting_btn")
                    : t("settings.connections.oauth_submit_btn")}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
