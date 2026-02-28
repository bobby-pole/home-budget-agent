import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CategoriesTab } from "@/components/settings/CategoriesTab";
import { TagsTab } from "@/components/settings/TagsTab";

export function SettingsPage() {
  return (
    <div className="p-4 md:p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Ustawienia</h2>
          <p className="text-muted-foreground">
            Zarządzaj kategoriami wydatków i tagami.
          </p>
        </div>
        
        <Tabs defaultValue="categories" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="categories">Kategorie</TabsTrigger>
            <TabsTrigger value="tags">Tagi</TabsTrigger>
          </TabsList>
          <TabsContent value="categories" className="mt-6">
            <CategoriesTab />
          </TabsContent>
          <TabsContent value="tags" className="mt-6">
            <TagsTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}