import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CategoriesTab } from "@/components/settings/CategoriesTab";
import { TagsTab } from "@/components/settings/TagsTab";
import { AccountsTab } from "@/components/settings/AccountsTab";
import { ConnectionsTab } from "@/components/settings/ConnectionsTab";
import { LanguageTab } from "@/components/settings/LanguageTab";
import { t } from "@/lib/i18n";

export function SettingsPage() {
  return (
    <div className="p-4 md:p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">{t("settings.page.title")}</h2>
          <p className="text-muted-foreground">
            {t("settings.page.description")}
          </p>
        </div>

        <Tabs defaultValue="categories" className="w-full">
          <TabsList className="grid w-full grid-cols-2 sm:grid-cols-5 h-auto gap-1">
            <TabsTrigger value="categories">{t("settings.page.tab_categories")}</TabsTrigger>
            <TabsTrigger value="tags">{t("settings.page.tab_tags")}</TabsTrigger>
            <TabsTrigger value="accounts">{t("settings.page.tab_accounts")}</TabsTrigger>
            <TabsTrigger value="connections">{t("settings.page.tab_connections")}</TabsTrigger>
            <TabsTrigger value="language">{t("settings.page.tab_language")}</TabsTrigger>
          </TabsList>
          <TabsContent value="categories" className="mt-6">
            <CategoriesTab />
          </TabsContent>
          <TabsContent value="tags" className="mt-6">
            <TagsTab />
          </TabsContent>
          <TabsContent value="accounts" className="mt-6">
            <AccountsTab />
          </TabsContent>
          <TabsContent value="connections" className="mt-6">
            <ConnectionsTab />
          </TabsContent>
          <TabsContent value="language" className="mt-6">
            <LanguageTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}