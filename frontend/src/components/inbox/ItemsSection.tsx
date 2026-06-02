import { useMemo } from "react";
import type {
  UseFormReturn,
  UseFieldArrayAppend,
  UseFieldArrayRemove,
  FieldArrayWithId,
} from "react-hook-form";
import { useWatch } from "react-hook-form";
import { Plus, Trash2, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { t } from "@/lib/i18n";
import { getIntlLocale } from "@/lib/dates";
import { CATEGORY_LABELS } from "@/lib/constants";
import type { CategoryRead } from "@/client";
import type { VerificationFormValues } from "./VerificationCard";

type LineFormShape = VerificationFormValues["lines"][number];

interface ItemsSectionProps {
  form: UseFormReturn<VerificationFormValues>;
  fields: FieldArrayWithId<VerificationFormValues, "lines", "id">[];
  append: UseFieldArrayAppend<VerificationFormValues, "lines">;
  remove: UseFieldArrayRemove;
  categories: CategoryRead[];
  collapsedRows: Record<string, boolean>;
  onToggleCollapse: (id: string) => void;
  onCollapseAll: () => void;
  onExpandAll: () => void;
}

const blankItem: LineFormShape = {
  name: "",
  unit_price: 0,
  quantity: 1,
  discount_total: 0,
  category_id: "",
  is_adjustment: false,
};

const blankAdjustment: LineFormShape = {
  name: "",
  unit_price: 0,
  quantity: 1,
  discount_total: 0,
  category_id: "",
  is_adjustment: true,
};

function formatMoney(value: number): string {
  return value.toLocaleString(getIntlLocale(), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function ItemsSection({
  form,
  fields,
  append,
  remove,
  categories,
  collapsedRows,
  onToggleCollapse,
  onCollapseAll,
  onExpandAll,
}: ItemsSectionProps) {
  // Watch all lines so basket-adjustment rows update reactively when edited.
  const watchedLines = useWatch({ control: form.control, name: "lines" });

  // Partition indices by adjustment flag, preserving stable form indices.
  const { productIndices, adjustmentIndices } = useMemo(() => {
    const lines = watchedLines ?? [];
    const products: number[] = [];
    const adjustments: number[] = [];
    fields.forEach((_, idx) => {
      if (lines[idx]?.is_adjustment) {
        adjustments.push(idx);
      } else {
        products.push(idx);
      }
    });
    return { productIndices: products, adjustmentIndices: adjustments };
  }, [fields, watchedLines]);

  const allCollapsed =
    productIndices.length > 0 &&
    productIndices.every((idx) => !!collapsedRows[fields[idx].id]);

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-bold uppercase tracking-widest text-muted-foreground/70">
            {t("inbox.verification_card.items_section_header")}
          </h3>
          <div className="flex items-center gap-2">
            {productIndices.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={allCollapsed ? onExpandAll : onCollapseAll}
                className="h-8 text-xs text-muted-foreground hover:text-primary transition-colors shrink-0 gap-1"
              >
                {allCollapsed ? (
                  <>
                    <ChevronDown className="h-3.5 w-3.5" />
                    {t("inbox.verification_card.expand_all")}
                  </>
                ) : (
                  <>
                    <ChevronUp className="h-3.5 w-3.5" />
                    {t("inbox.verification_card.collapse_all")}
                  </>
                )}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => append(blankItem)}
              className="h-8 text-xs gap-1 border-primary/20 hover:bg-primary/5 hover:text-primary transition-colors shrink-0"
            >
              <Plus className="h-3 w-3" /> {t("inbox.verification_card.add_item_button")}
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          {productIndices.map((index) => (
            <ItemRow
              key={fields[index].id}
              form={form}
              index={index}
              categories={categories}
              onRemove={() => remove(index)}
              isCollapsed={!!collapsedRows[fields[index].id]}
              onToggleCollapse={() => onToggleCollapse(fields[index].id)}
            />
          ))}
        </div>
      </div>

      <AdjustmentsSection
        form={form}
        fields={fields}
        adjustmentIndices={adjustmentIndices}
        onAppend={() => append(blankAdjustment)}
        onRemove={remove}
      />
    </div>
  );
}

interface ItemRowProps {
  form: UseFormReturn<VerificationFormValues>;
  index: number;
  categories: CategoryRead[];
  onRemove: () => void;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

function ItemRow({
  form,
  index,
  categories,
  onRemove,
  isCollapsed,
  onToggleCollapse,
}: ItemRowProps) {
  // Watch just this row so the computed gross/total update as the user types
  // without re-rendering siblings.
  const name = useWatch({ control: form.control, name: `lines.${index}.name` }) || "";
  const categoryId = useWatch({ control: form.control, name: `lines.${index}.category_id` }) || "";
  const unitPrice = useWatch({ control: form.control, name: `lines.${index}.unit_price` }) ?? 0;
  const qty = useWatch({ control: form.control, name: `lines.${index}.quantity` }) ?? 1;
  const discount = useWatch({ control: form.control, name: `lines.${index}.discount_total` }) ?? 0;

  const gross = (Number(unitPrice) || 0) * (Number(qty) || 0);
  const total = gross + (Number(discount) || 0);

  const selectedCategory = categories.find((c) => c.id.toString() === categoryId);

  if (isCollapsed) {
    return (
      <div
        onClick={onToggleCollapse}
        className="group relative bg-card border border-border/40 hover:border-primary/30 p-2 sm:p-3 rounded-xl flex items-center justify-between gap-3 cursor-pointer hover:shadow-sm transition-all"
      >
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          {/* Category Icon */}
          <div className="size-8 rounded-full flex items-center justify-center bg-muted text-base shrink-0 select-none">
            {selectedCategory?.icon || "💰"}
          </div>

          {/* Name & Qty/Price Summary */}
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-sm font-bold truncate pr-2">
              {name || (
                <span className="text-muted-foreground/50 italic">
                  {t("inbox.verification_card.placeholder_item_name")}
                </span>
              )}
            </span>
            <span className="text-[10px] text-muted-foreground font-semibold flex items-center gap-1.5 mt-0.5">
              {qty !== 1 && (
                <span className="tabular-nums">
                  {qty} × {formatMoney(unitPrice)} {t("common.currency")}
                </span>
              )}
              {discount < 0 && (
                <span className="text-emerald-600 dark:text-emerald-400 tabular-nums">
                  {t("inbox.verification_card.label_discount")}: {formatMoney(discount)} {t("common.currency")}
                </span>
              )}
            </span>
          </div>
        </div>

        {/* Right side: total price + action buttons */}
        <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
          <div className="text-right flex flex-col justify-center select-none">
            <span className="text-sm font-black tabular-nums">
              {formatMoney(total)} {t("common.currency")}
            </span>
          </div>

          <div className="flex items-center gap-0.5">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={onToggleCollapse}
              className="h-8 w-8 text-muted-foreground hover:text-foreground shrink-0"
              aria-label={t("inbox.verification_card.expand_item")}
            >
              <ChevronDown className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={onRemove}
              className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10 shrink-0"
              aria-label={t("inbox.verification_card.remove_item")}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group relative bg-card border border-border/40 p-3 rounded-xl hover:border-primary/30 transition-all hover:shadow-sm">
      <div className="flex flex-col gap-2">
        {/* Row 1: name + category + toggle collapse + delete */}
        <div className="flex gap-2 items-start">
          <FormField
            control={form.control}
            name={`lines.${index}.name`}
            render={({ field }) => (
              <FormItem className="flex-1 space-y-0">
                <FormControl>
                  <Input
                    {...field}
                    placeholder={t("inbox.verification_card.placeholder_item_name")}
                    className="h-9 text-sm bg-muted/20"
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name={`lines.${index}.category_id`}
            render={({ field }) => (
              <FormItem className="w-32 space-y-0">
                <Select onValueChange={field.onChange} value={field.value || undefined}>
                  <FormControl>
                    <SelectTrigger className="h-9 text-xs bg-muted/20 px-2">
                      <SelectValue placeholder={t("inbox.verification_card.placeholder_category")} />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {categories.map((cat) => (
                      <SelectItem key={cat.id} value={cat.id.toString()}>
                        <span className="flex items-center gap-2">
                          <span>{cat.icon}</span>
                          <span className="truncate max-w-[80px]">
                            {cat.is_system ? (CATEGORY_LABELS[cat.name] || cat.name) : cat.name}
                          </span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormItem>
            )}
          />
          <div className="flex items-center gap-0.5 shrink-0">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={onToggleCollapse}
              className="h-9 w-9 text-muted-foreground hover:text-foreground shrink-0"
              aria-label={t("inbox.verification_card.collapse_item")}
            >
              <ChevronUp className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={onRemove}
              className="h-9 w-9 text-muted-foreground hover:text-destructive hover:bg-destructive/10 shrink-0"
              aria-label={t("inbox.verification_card.remove_item")}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Row 2: unit × qty = gross  (all editable except gross, which is computed) */}
        <div className="flex items-center gap-1.5 text-xs">
          <FormField
            control={form.control}
            name={`lines.${index}.unit_price`}
            render={({ field }) => (
              <FormItem className="w-20 space-y-0">
                <FormControl>
                  <div className="relative">
                    <Input
                      type="number"
                      step="0.01"
                      {...field}
                      onChange={(e) => field.onChange(parseFloat(e.target.value) || 0)}
                      className="h-8 text-xs bg-muted/20 pr-5 text-right tabular-nums"
                      title={t("inbox.verification_card.label_unit_price")}
                    />
                    <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">{t("common.currency")}</span>
                  </div>
                </FormControl>
              </FormItem>
            )}
          />
          <span className="text-muted-foreground">×</span>
          <FormField
            control={form.control}
            name={`lines.${index}.quantity`}
            render={({ field }) => (
              <FormItem className="w-14 space-y-0">
                <FormControl>
                  <div className="relative">
                    <Input
                      type="number"
                      step="0.01"
                      {...field}
                      onChange={(e) => field.onChange(parseFloat(e.target.value) || 0)}
                      className="h-8 text-xs bg-muted/20 pr-5 text-right tabular-nums"
                      title={t("inbox.verification_card.label_quantity")}
                    />
                    <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">{t("common.unit_pcs")}</span>
                  </div>
                </FormControl>
              </FormItem>
            )}
          />
          <span className="text-muted-foreground">=</span>
          <span className="font-medium text-muted-foreground/80 tabular-nums w-20 text-right shrink-0">
            {formatMoney(gross)} {t("common.currency")}
          </span>
        </div>

        {/* Row 3: discount  |  final line total */}
        <div className="flex items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground shrink-0">{t("inbox.verification_card.label_discount")}:</span>
            <FormField
              control={form.control}
              name={`lines.${index}.discount_total`}
              render={({ field }) => (
                <FormItem className="w-21 space-y-0">
                  <FormControl>
                    <div className="relative">
                      <Input
                        type="number"
                        step="0.01"
                        max={0}
                        {...field}
                        onChange={(e) => {
                          const raw = parseFloat(e.target.value);
                          // discount is always ≤ 0; clamp positive input
                          field.onChange(isNaN(raw) ? 0 : Math.min(0, raw));
                        }}
                        className="h-8 text-xs bg-muted/20 pr-5 text-right tabular-nums text-emerald-600 dark:text-emerald-400"
                      />
                      <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">{t("common.currency")}</span>
                    </div>
                  </FormControl>
                </FormItem>
              )}
            />
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-muted-foreground uppercase tracking-wide text-[10px] font-semibold">
              {t("inbox.verification_card.label_total")}
            </span>
            <span className="text-sm font-bold tabular-nums">
              {formatMoney(total)} {t("common.currency")}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

interface AdjustmentsSectionProps {
  form: UseFormReturn<VerificationFormValues>;
  fields: FieldArrayWithId<VerificationFormValues, "lines", "id">[];
  adjustmentIndices: number[];
  onAppend: () => void;
  onRemove: (index: number) => void;
}

function AdjustmentsSection({ form, fields, adjustmentIndices, onAppend, onRemove }: AdjustmentsSectionProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-bold uppercase tracking-widest text-muted-foreground/70">
          {t("inbox.verification_card.basket_adjustments_section_header")}
        </h3>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onAppend}
          className="h-8 text-xs gap-1 border-amber-500/30 hover:bg-amber-500/5 hover:text-amber-700 dark:hover:text-amber-400 transition-colors shrink-0"
        >
          <Plus className="h-3 w-3" /> {t("inbox.verification_card.add_adjustment_button")}
        </Button>
      </div>

      {adjustmentIndices.length === 0 ? (
        <p className="text-xs text-muted-foreground italic px-1">
          {t("inbox.verification_card.no_basket_adjustments")}
        </p>
      ) : (
        <div className="space-y-2">
          {adjustmentIndices.map((index) => (
            <AdjustmentRow
              key={fields[index].id}
              form={form}
              index={index}
              onRemove={() => onRemove(index)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface AdjustmentRowProps {
  form: UseFormReturn<VerificationFormValues>;
  index: number;
  onRemove: () => void;
}

function AdjustmentRow({ form, index, onRemove }: AdjustmentRowProps) {
  return (
    <div className="flex items-start gap-2 px-3 py-2 rounded-xl border border-amber-500/30 bg-amber-500/5">
      <FormField
        control={form.control}
        name={`lines.${index}.name`}
        render={({ field }) => (
          <FormItem className="flex-1 space-y-0">
            <FormControl>
              <Input
                {...field}
                placeholder={t("inbox.verification_card.placeholder_adjustment_name")}
                className="h-8 text-xs bg-transparent border-amber-500/20 text-amber-700 dark:text-amber-400 placeholder:text-amber-700/50"
              />
            </FormControl>
            <FormMessage className="text-[10px]" />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name={`lines.${index}.unit_price`}
        render={({ field }) => (
          <FormItem className="w-24 space-y-0">
            <FormControl>
              <div className="relative">
                <Input
                  type="number"
                  step="0.01"
                  {...field}
                  onChange={(e) => field.onChange(parseFloat(e.target.value) || 0)}
                  className="h-8 text-xs bg-transparent border-amber-500/20 pr-5 text-right tabular-nums font-semibold text-amber-700 dark:text-amber-400"
                />
                <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[10px] text-amber-700/60">{t("common.currency")}</span>
              </div>
            </FormControl>
          </FormItem>
        )}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onRemove}
        className="h-8 w-8 text-amber-700/70 hover:text-destructive hover:bg-destructive/10 shrink-0"
        aria-label={t("inbox.verification_card.remove_item")}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
