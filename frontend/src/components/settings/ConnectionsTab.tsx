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
  ConnectionOAuthStartResponse,
  ExternalReceiptConnectionCreate,
  ExternalReceiptConnectionRead,
} from "@/client";
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
import { Store, RefreshCw, Unplug, Plus, ShieldCheck, AlertTriangle, Clock, ExternalLink, KeyRound } from "lucide-react";

const STORES = [
  { id: "lidl", name: "Lidl Plus", icon: "/brands/lidl.svg" },
  { id: "biedronka", name: "Biedronka", icon: "/brands/biedronka.ico" },
];

export function ConnectionsTab() {
  const queryClient = useQueryClient();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [formData, setFormData] = useState<ExternalReceiptConnectionCreate>({
    provider: "lidl",
  });
  const [oauthSession, setOauthSession] = useState<ConnectionOAuthStartResponse | null>(null);
  const [callbackInput, setCallbackInput] = useState("");

  const { data: connections = [], isLoading } = useQuery({
    queryKey: ["connections"],
    queryFn: api.getConnections,
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
      setCallbackInput("");
      toast.success(t("settings.connections.toast_oauth_success"));
    },
    onError: () => toast.error(t("common.error")),
  });

  const syncNowMutation = useMutation({
    mutationFn: (id: number) => api.syncNowConnection(id),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
      toast.success(res.message || t("settings.connections.toast_sync_queued"));
    },
    onError: () => toast.error(t("common.error")),
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
                      <div className="flex justify-between text-destructive">
                        <span>{t("settings.connections.status_sync_error")}:</span>
                        <span className="font-mono text-[11px]">{conn.last_error_code}</span>
                      </div>
                    )}
                  </div>
                </div>

                {!conn.has_token && conn.status === "reauth_required" && (
                  <p className="text-sm text-muted-foreground">{t("settings.connections.authorization_unavailable")}</p>
                )}

                {/* Actions */}
                <div className="flex flex-wrap items-center justify-end gap-2 pt-1 border-t">
                  {conn.provider === "lidl" && conn.status !== "active" && (
                    <Button
                      size="sm"
                      variant="default"
                      disabled={startOAuthMutation.isPending}
                      onClick={() => startOAuthMutation.mutate(conn.id)}
                      className="gap-1.5"
                    >
                      <KeyRound className="size-3.5" />
                      {t("settings.connections.authorize_lidl_btn")}
                    </Button>
                  )}

                  <Button
                    size="sm"
                    variant="outline"
                    disabled={conn.status !== "active" || !conn.has_token || syncNowMutation.isPending}
                    onClick={() => syncNowMutation.mutate(conn.id)}
                    className="gap-1.5"
                  >
                    <RefreshCw className={`size-3.5 ${syncNowMutation.isPending ? "animate-spin" : ""}`} />
                    {syncNowMutation.isPending
                      ? t("settings.connections.syncing_btn")
                      : t("settings.connections.sync_now_btn")}
                  </Button>

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
        open={Boolean(oauthSession)}
        onOpenChange={(open) => {
          if (!open) {
            setOauthSession(null);
            setCallbackInput("");
          }
        }}
      >
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>{t("settings.connections.oauth_modal_title")}</DialogTitle>
          </DialogHeader>
          {oauthSession && (
            <div className="space-y-4 py-2">
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
