import { useState, useEffect, useRef } from "react";
import { useForm, useFieldArray, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { t } from "@/lib/i18n";
import { format } from "date-fns";
import {
  AlertTriangle,
  Check,
  Trash2,
  ImageIcon,
  Loader2,
  Calendar as CalendarIcon,
  Store,
  DollarSign,
  ArrowLeft,
  FileText,
  FileJson,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage
} from "@/components/ui/form";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { api, apiClient } from "@/lib/api";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { TransactionRead as Transaction } from "@/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { translateValidationMessage } from "@/lib/errorCodes";
import { ItemsSection } from "./ItemsSection";

const lineSchema = z.object({
  id: z.number().optional(),
  name: z.string().min(1, t("inbox.verification_card.validation.name_required")),
  // Unit price BEFORE any discount (per piece / per kg) for regular items.
  // For basket adjustments (kaucja, basket coupons) this holds the (negative)
  // refund amount, so no lower bound here.
  unit_price: z.number(),
  quantity: z.number().min(0.01),
  // total discount on this line (always ≤ 0)
  discount_total: z.number().max(0),
  category_id: z.string().optional(),
  category_source: z.string().optional(),
  // True for basket-level adjustments (kaucja, basket coupons). UI hides
  // category/qty for these and renders them in a dedicated footer section.
  is_adjustment: z.boolean(),
});

const verificationSchema = z.object({
  merchant_name: z.string().min(1, t("inbox.verification_card.validation.merchant_required")),
  date: z.string(),
  total_amount: z.number().min(0),
  currency: z.string(),
  lines: z.array(lineSchema),
  keep_image: z.boolean(),
});

export type VerificationFormValues = z.infer<typeof verificationSchema>;

interface VerificationCardProps {
  transaction: Transaction;
  onSuccess: () => void;
  onBack?: () => void;
}

export function VerificationCard({ transaction, onSuccess, onBack }: VerificationCardProps) {
  const queryClient = useQueryClient();
  const [collapsedRows, setCollapsedRows] = useState<Record<string, boolean>>({});
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageType, setImageType] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(true);
  const [zoom, setZoom] = useState(1);
  const zoomRef = useRef(1);
  const previewRef = useRef<HTMLDivElement>(null);

  // Reset zoom when a new image loads (setState-during-render pattern — avoids effect)
  const [prevImageUrl, setPrevImageUrl] = useState(imageUrl);
  if (imageUrl !== prevImageUrl) {
    setPrevImageUrl(imageUrl);
    setZoom(1);
  }

  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  // Effect to fetch image with Auth token
  useEffect(() => {
    let objectUrl: string | null = null;

    async function loadImage() {
      setImageLoading(true);
      try {
        const response = await apiClient.get(`/transactions/${transaction.id}/receipt`, {
          responseType: 'blob'
        });
        setImageType(response.data.type);
        objectUrl = URL.createObjectURL(response.data);
        setImageUrl(objectUrl);
      } catch (error) {
        console.error("Failed to load receipt image:", error);
        setImageUrl(null);
      } finally {
        setImageLoading(false);
      }
    }

    loadImage();

    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [transaction.id]);

  useEffect(() => {
    const el = previewRef.current;
    if (!el || !imageUrl) return;

    zoomRef.current = 1;

    // Ctrl+Wheel (or trackpad pinch) → zoom toward cursor
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const oldZoom = zoomRef.current;
      const newZoom = Math.min(Math.max(0.5, oldZoom * (e.deltaY > 0 ? 0.9 : 1.1)), 5);
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const sx = el.scrollLeft + mx;
      const sy = el.scrollTop + my;
      zoomRef.current = newZoom;
      setZoom(newZoom);
      requestAnimationFrame(() => {
        const r = newZoom / oldZoom;
        el.scrollLeft = sx * r - mx;
        el.scrollTop = sy * r - my;
      });
    };

    // Mouse drag → pan
    let dragging = false, lx = 0, ly = 0;
    const onMouseDown = (e: MouseEvent) => {
      if (e.button !== 0) return;
      dragging = true; lx = e.clientX; ly = e.clientY;
      el.style.cursor = 'grabbing';
      e.preventDefault();
    };
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging) return;
      el.scrollLeft -= e.clientX - lx;
      el.scrollTop -= e.clientY - ly;
      lx = e.clientX; ly = e.clientY;
    };
    const onMouseUp = () => {
      if (dragging) { dragging = false; el.style.cursor = 'grab'; }
    };
    const onDblClick = () => {
      zoomRef.current = 1;
      setZoom(1);
    };

    // Touch pinch → zoom (single finger scroll handled natively by overflow-auto)
    let lastDist: number | null = null;
    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 2) {
        lastDist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY,
        );
      }
    };
    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length !== 2 || lastDist === null) return;
      e.preventDefault();
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
      const newZoom = Math.min(Math.max(0.5, zoomRef.current * (dist / lastDist)), 5);
      zoomRef.current = newZoom;
      setZoom(newZoom);
      lastDist = dist;
    };
    const onTouchEnd = () => { lastDist = null; };

    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    el.addEventListener('dblclick', onDblClick);
    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove', onTouchMove, { passive: false });
    el.addEventListener('touchend', onTouchEnd, { passive: true });

    return () => {
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      el.removeEventListener('dblclick', onDblClick);
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      el.removeEventListener('touchend', onTouchEnd);
    };
  }, [imageUrl]);

  const form = useForm<VerificationFormValues>({
    resolver: zodResolver(verificationSchema),
    defaultValues: {
      merchant_name: transaction.merchant_name || "",
      date: transaction.date ? format(new Date(transaction.date), "yyyy-MM-dd") : format(new Date(), "yyyy-MM-dd"),
      total_amount: transaction.total_amount || 0,
      currency: transaction.currency || "PLN",
      lines: (transaction.lines || []).map(l => ({
        id: l.id,
        name: l.name,
        // Prefer pre-discount unit price; fall back to current per-unit price
        // (which equals unit price when there is no discount).
        unit_price: l.original_price ?? l.price ?? 0,
        quantity: l.quantity || 1,
        discount_total: l.discount_total ?? 0,
        category_id: l.category_id?.toString() || "",
        category_source: l.category_source || "",
        is_adjustment: l.is_adjustment ?? false,
      })),
      keep_image: false,
    },
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "lines",
  });

  const [isSubmitting, setIsSubmitting] = useState(false);

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteTransaction(transaction.id),
    onSuccess: () => {
      toast.success(t("inbox.verification_card.toast_deleted"));
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["budget-summary"] });
      onSuccess();
    },
    onError: () => {
      toast.error(t("inbox.verification_card.toast_delete_error"));
    }
  });

  const onSubmit = async (values: VerificationFormValues) => {
    setIsSubmitting(true);
    try {
      await api.verifyTransaction(
        transaction.id,
        {
          merchant_name: values.merchant_name,
          date: values.date,
          total_amount: values.total_amount,
          currency: values.currency,
        },
        values.lines.map(l => {
          // For adjustments we keep the user-entered unit_price as-is (single line, qty=1).
          // For regular items: line gross = unit_price × qty; final per-unit = unit + discount/qty.
          const qty = l.quantity || 1;
          const gross = l.unit_price * qty;
          const finalLineTotal = gross + l.discount_total;
          const finalUnit = qty > 0 ? finalLineTotal / qty : finalLineTotal;
          return {
            name: l.name,
            price: finalUnit,
            quantity: qty,
            category_id: l.category_id ? parseInt(l.category_id) : undefined,
            original_price: l.discount_total < 0 || l.is_adjustment ? l.unit_price : null,
            discount_total: l.discount_total,
            final_price: l.discount_total < 0 ? finalUnit : null,
            is_adjustment: l.is_adjustment,
          };
        }),
        values.keep_image
      );
      toast.success(t("inbox.verification_card.toast_verified"));
      onSuccess();
    } catch (error) {
      console.error("Verification error:", error);
      toast.error(t("inbox.verification_card.toast_verify_error"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const parseNumber = (val: string | number): number => {
    if (typeof val === "number") return val;
    if (typeof val === "string") {
      const clean = val.replace(",", ".");
      const parsed = parseFloat(clean);
      return isNaN(parsed) ? 0 : parsed;
    }
    return 0;
  };

  const lines = useWatch({ control: form.control, name: "lines" }) || [];
  const linesTotal = lines.reduce((acc, l) => {
    if (l.is_adjustment) {
      return acc + parseNumber(l.unit_price);
    }
    const unit = parseNumber(l.unit_price);
    const qty = parseNumber(l.quantity);
    const disc = parseNumber(l.discount_total);
    return acc + (unit * qty + disc);
  }, 0);

  const receiptPreview = (
    <Card className="flex flex-col h-full bg-card/50 backdrop-blur-sm border-border/50 overflow-hidden shadow-sm">
      <CardHeader className="py-3 px-4 border-b shrink-0">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <ImageIcon className="h-4 w-4 text-primary" />
          {t("inbox.verification_card.receipt_preview_title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 p-0 overflow-hidden bg-black/5 relative flex items-center justify-center">
        {imageLoading ? (
          <div className="flex flex-col items-center gap-2 text-muted-foreground/40">
            <Loader2 className="h-8 w-8 animate-spin" />
            <p className="text-xs font-medium">{t("inbox.verification_card.image_loading")}</p>
          </div>
        ) : imageType === "application/json" ? (
          <div className="flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
            <FileJson className="h-12 w-12 mb-4 opacity-20" />
            <p className="font-medium text-sm">{t("inbox.no_preview")}</p>
            <p className="text-xs mt-1 max-w-[200px]">{t("inbox.no_visual_rep")}</p>
          </div>
        ) : imageUrl ? (
          <>
            <div
              ref={previewRef}
              className="absolute inset-0 overflow-auto"
              style={{ cursor: imageType === 'application/pdf' ? 'auto' : 'grab' }}
            >
              <div style={{
                width: imageType === 'application/pdf' ? '100%' : `${Math.max(zoom, 1) * 100}%`,
                minHeight: '100%',
                height: imageType === 'application/pdf' ? '100%' : 'auto',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                {imageType === 'application/pdf' ? (
                  <iframe
                    src={`${imageUrl}#toolbar=0&navpanes=0`}
                    title="Receipt PDF Preview"
                    className="w-full h-full border-0"
                    style={{ minHeight: '500px' }}
                  />
                ) : (
                  <img
                    src={imageUrl}
                    alt="Receipt preview"
                    style={{
                      width: zoom >= 1 ? '100%' : `${zoom * 100}%`,
                      height: 'auto',
                      display: 'block',
                      userSelect: 'none',
                      pointerEvents: 'none',
                    }}
                    draggable={false}
                  />
                )}
              </div>
            </div>
            {imageType !== 'application/pdf' && (
              <div className="absolute bottom-2 right-2 z-20 flex items-center gap-0.5 bg-background/90 backdrop-blur-sm rounded-lg px-1.5 py-1 border shadow-sm">
                <button
                  type="button"
                  onClick={() => setZoom(z => { const n = Math.max(0.5, z * 0.8); zoomRef.current = n; return n; })}
                  className="w-6 h-6 flex items-center justify-center text-sm font-bold hover:text-primary transition-colors"
                >−</button>
                <span className="text-[10px] w-9 text-center tabular-nums text-muted-foreground">
                  {Math.round(zoom * 100)}%
                </span>
                <button
                  type="button"
                  onClick={() => setZoom(z => { const n = Math.min(5, z * 1.25); zoomRef.current = n; return n; })}
                  className="w-6 h-6 flex items-center justify-center text-sm font-bold hover:text-primary transition-colors"
                >+</button>
                <button
                  type="button"
                  onClick={() => { zoomRef.current = 1; setZoom(1); }}
                  className="w-6 h-6 flex items-center justify-center text-xs text-muted-foreground hover:text-primary transition-colors"
                  title="Reset zoom"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="flex flex-col items-center justify-center text-muted-foreground/20">
            <ImageIcon className="h-24 w-24" />
            <p className="text-xs font-medium">{t("inbox.verification_card.image_load_error")}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="hidden lg:grid grid-cols-2 gap-6 h-full overflow-hidden">
        {receiptPreview}
        {renderForm()}
      </div>

      <div className="lg:hidden flex flex-col h-full overflow-hidden">
        <Tabs defaultValue="form" className="flex-1 flex flex-col overflow-hidden">
          <div className="px-4 py-2 border-b bg-background shrink-0">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="form" className="flex items-center gap-2">
                <FileText className="h-4 w-4" /> {t("inbox.verification_card.tab_form")}
              </TabsTrigger>
              <TabsTrigger value="receipt" className="flex items-center gap-2">
                <ImageIcon className="h-4 w-4" /> {t("inbox.verification_card.tab_receipt")}
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="form" className="flex-1 data-[state=active]:flex flex-col overflow-hidden m-0 p-0 min-h-0">
            {renderForm(true)}
          </TabsContent>
          <TabsContent value="receipt" className="flex-1 data-[state=active]:flex flex-col overflow-hidden m-0 p-0 min-h-0">
            {receiptPreview}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );

  function renderForm(isMobileView = false) {
    return (
      <Card className={cn(
        "flex flex-col h-full bg-card shadow-lg border-border/50 overflow-hidden",
        isMobileView && "border-none shadow-none rounded-none"
      )}>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col h-full overflow-hidden">
            <CardHeader className="py-4 px-6 border-b shrink-0">
              <div className="flex justify-between items-center gap-4">
                <div className="flex items-center gap-2 min-w-0">
                  {onBack && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={onBack}
                      className="h-9 w-9 -ml-2 shrink-0"
                    >
                      <ArrowLeft className="h-5 w-5" />
                    </Button>
                  )}
                  <CardTitle className="text-lg md:text-xl font-bold truncate">{t("inbox.verification_card.title")}</CardTitle>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                        disabled={deleteMutation.isPending || isSubmitting}
                      >
                        {deleteMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>{t("inbox.verification_card.delete_dialog_title")}</AlertDialogTitle>
                        <AlertDialogDescription>
                          {t("inbox.verification_card.delete_dialog_description")}
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>{t("inbox.verification_card.delete_dialog_cancel")}</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => deleteMutation.mutate()}
                          className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        >
                          {t("inbox.verification_card.delete_dialog_confirm")}
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>

                  <Button
                    type="submit"
                    disabled={isSubmitting || deleteMutation.isPending}
                    className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-md"
                  >
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Check className="h-4 w-4 mr-2" />}
                    <span className="hidden sm:inline">{isSubmitting ? t("inbox.verification_card.save_pending") : t("inbox.verification_card.save_idle")}</span>
                    <span className="sm:hidden">OK</span>
                  </Button>
                </div>
              </div>
            </CardHeader>

            {transaction.receipt_scan?.validation_message && (
              <div className="mx-4 md:mx-6 mt-4 flex items-start gap-3 rounded-lg border border-yellow-400/40 bg-yellow-400/10 px-4 py-3 text-sm text-yellow-700 dark:text-yellow-300">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{translateValidationMessage(transaction.receipt_scan.validation_message)}</span>
              </div>
            )}

            <CardContent className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 custom-scrollbar">
              <div className="bg-muted/30 p-4 rounded-xl border border-border/50 space-y-4">
                <FormField
                  control={form.control}
                  name="merchant_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        <Store className="h-3 w-3" /> {t("inbox.verification_card.field_merchant")}
                      </FormLabel>
                      <FormControl>
                        <Input {...field} className="bg-background/80 border-border/50 focus:border-primary/50 transition-colors" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="date"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                          <CalendarIcon className="h-3 w-3" /> {t("inbox.verification_card.field_date")}
                        </FormLabel>
                        <FormControl>
                          <Input type="date" {...field} className="bg-background/80 border-border/50 focus:border-primary/50" />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="total_amount"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                          <DollarSign className="h-3 w-3" /> {t("inbox.verification_card.field_total")}
                        </FormLabel>
                        <FormControl>
                          <div className="relative">
                            <Input
                              type="number"
                              step="0.01"
                              {...field}
                              onChange={(e) => field.onChange(parseFloat(e.target.value) || 0)}
                              className="bg-background/80 border-border/50 focus:border-primary/50 pr-12"
                            />
                            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-bold text-muted-foreground">
                              {form.getValues("currency")}
                            </span>
                          </div>
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </div>

              <ItemsSection
                form={form}
                fields={fields}
                append={append}
                remove={remove}
                categories={categories}
                collapsedRows={collapsedRows}
                onToggleCollapse={(id) => setCollapsedRows(prev => ({ ...prev, [id]: !prev[id] }))}
                onCollapseAll={() => {
                  const newMap: Record<string, boolean> = {};
                  const lines = form.getValues("lines") || [];
                  fields.forEach((f, idx) => {
                    if (f.id && !lines[idx]?.is_adjustment) {
                      newMap[f.id] = true;
                    }
                  });
                  setCollapsedRows(newMap);
                }}
                onExpandAll={() => setCollapsedRows({})}
              />

            </CardContent>

            <CardFooter className="py-4 px-4 md:px-6 border-t bg-muted/30 shrink-0">
              <div className="flex flex-col sm:flex-row justify-between items-center w-full gap-3">
                <FormField
                  control={form.control}
                  name="keep_image"
                  render={({ field }) => (
                    <FormItem className="flex items-center gap-2 space-y-0">
                      <FormControl>
                        <input
                          type="checkbox"
                          id="keep_image"
                          checked={field.value}
                          onChange={field.onChange}
                          className="h-4 w-4 rounded border-border accent-primary cursor-pointer"
                        />
                      </FormControl>
                      <FormLabel
                        htmlFor="keep_image"
                        className="text-xs text-muted-foreground font-normal cursor-pointer select-none"
                      >
                        {t("inbox.verification_card.keep_image_label")}
                      </FormLabel>
                    </FormItem>
                  )}
                />
                <div className="text-xs md:text-sm font-bold shrink-0">
                  {t("inbox.verification_card.sum_prefix")} {linesTotal.toFixed(2)} {form.getValues("currency")}
                </div>
              </div>
            </CardFooter>
          </form>
        </Form>
      </Card>
    );
  }
}
