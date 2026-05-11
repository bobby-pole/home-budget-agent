import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CategoriesTab } from "@/components/settings/CategoriesTab";
import { TagsTab } from "@/components/settings/TagsTab";
import { BudgetTab } from "@/components/settings/BudgetTab";
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
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="categories">{t("settings.page.tab_categories")}</TabsTrigger>
            <TabsTrigger value="tags">{t("settings.page.tab_tags")}</TabsTrigger>
            <TabsTrigger value="budget">{t("settings.page.tab_budget")}</TabsTrigger>
            <TabsTrigger value="language">{t("settings.page.tab_language")}</TabsTrigger>
          </TabsList>
          <TabsContent value="categories" className="mt-6">
            <CategoriesTab />
          </TabsContent>
          <TabsContent value="tags" className="mt-6">
            <TagsTab />
          </TabsContent>
          <TabsContent value="budget" className="mt-6">
            <BudgetTab />
          </TabsContent>
          <TabsContent value="language" className="mt-6">
            <LanguageTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}