import { Link } from "react-router-dom";
import { ArrowLeftRight, Landmark, Settings, LogOut, ChevronRight } from "lucide-react";
import { t } from "@/lib/i18n";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
export function MorePage() {
  const { logout } = useAuth();

  return (
    <div className="p-4 space-y-6 md:hidden">
      <h1 className="text-2xl font-bold">{t("more.title")}</h1>

      <div className="space-y-6">
        {/* Navigation Section */}
        <section>
          <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider mb-2 pl-1">
            {t("more.navigation")}
          </h2>
          <Card className="rounded-2xl border-border/50 overflow-hidden shadow-sm">
            <div className="divide-y divide-border/50">
              <Link to="/transactions" className="flex items-center justify-between p-4 hover:bg-muted/50 transition-colors">
                <div className="flex items-center gap-3">
                  <div className="size-8 rounded-full bg-blue-500/10 text-blue-500 flex items-center justify-center shrink-0">
                    <ArrowLeftRight className="size-4" />
                  </div>
                  <span className="font-medium">{t("transactions.page_title")}</span>
                </div>
                <ChevronRight className="size-5 text-muted-foreground" />
              </Link>
              <Link to="/accounts" className="flex items-center justify-between p-4 hover:bg-muted/50 transition-colors">
                <div className="flex items-center gap-3">
                  <div className="size-8 rounded-full bg-emerald-500/10 text-emerald-500 flex items-center justify-center shrink-0">
                    <Landmark className="size-4" />
                  </div>
                  <span className="font-medium">{t("accounts.title")}</span>
                </div>
                <ChevronRight className="size-5 text-muted-foreground" />
              </Link>
              <Link to="/profile" className="flex items-center justify-between p-4 hover:bg-muted/50 transition-colors">
                <div className="flex items-center gap-3">
                  <div className="size-8 rounded-full bg-purple-500/10 text-purple-500 flex items-center justify-center shrink-0">
                    <Settings className="size-4" />
                  </div>
                  <span className="font-medium">{t("profile.title")}</span>
                </div>
                <ChevronRight className="size-5 text-muted-foreground" />
              </Link>
            </div>
          </Card>
        </section>

        {/* Danger Zone */}
        <section className="pt-2">
          <Card className="rounded-2xl border-border/50 overflow-hidden shadow-sm py-1">
            <button
              onClick={logout}
              className="w-full flex items-center justify-between p-4 hover:bg-destructive/5 transition-colors text-destructive"
            >
              <div className="flex items-center gap-3">
                <div className="size-8 rounded-full bg-destructive/10 flex items-center justify-center shrink-0">
                  <LogOut className="size-4" />
                </div>
                <span className="font-medium">{t("nav.user_menu.logout")}</span>
              </div>
            </button>
          </Card>
        </section>
      </div>
    </div>
  );
}
