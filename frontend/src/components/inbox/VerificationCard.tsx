import { useState, useEffect } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { format } from "date-fns";
import {
  Check,
  Trash2,
  Plus,
  ImageIcon,
  AlertCircle,
  Loader2,
  Calendar as CalendarIcon,
  Store,
  DollarSign,
  ArrowLeft,
  FileText
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
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
import { api, apiClient } from "@/lib/api"; // Added apiClient for blob fetch
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { TransactionRead as Transaction } from "@/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const lineSchema = z.object({
  id: z.number().optional(),
  name: z.string().min(1, "Nazwa jest wymagana"),
  price: z.number().min(0),
  quantity: z.number().min(0.01),
  category_id: z.string().optional(),
});

const verificationSchema = z.object({
  merchant_name: z.string().min(1, "Nazwa sprzedawcy jest wymagana"),
  date: z.string(),
  total_amount: z.number().min(0),
  currency: z.string(),
  lines: z.array(lineSchema),
});

type VerificationFormValues = z.infer<typeof verificationSchema>;

interface VerificationCardProps {
  transaction: Transaction;
  onSuccess: () => void;
  onBack?: () => void;
}

export function VerificationCard({ transaction, onSuccess, onBack }: VerificationCardProps) {
  const queryClient = useQueryClient();
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(true);

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
        price: l.price || 0,
        quantity: l.quantity || 1,
        category_id: l.category_id?.toString() || "",
      })),
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
      toast.success("Paragon został odrzucony i usunięty");
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      onSuccess();
    },
    onError: () => {
      toast.error("Błąd podczas usuwania paragonu");
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
        values.lines.map(l => ({
          name: l.name,
          price: l.price,
          quantity: l.quantity,
          category_id: l.category_id ? parseInt(l.category_id) : undefined,
        }))
      );
      toast.success("Transakcja zweryfikowana pomyślnie");
      onSuccess();
    } catch (error) {
      console.error("Verification error:", error);
      toast.error("Wystąpił błąd podczas weryfikacji");
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

  const lines = form.watch("lines") || [];
  const linesTotal = lines.reduce((acc, l) => {
    const p = parseNumber(l.price);
    const q = parseNumber(l.quantity);
    return acc + (p * q);
  }, 0);

  const receiptPreview = (
    <Card className="flex flex-col h-full bg-card/50 backdrop-blur-sm border-border/50 overflow-hidden shadow-sm">
      <CardHeader className="py-3 px-4 border-b shrink-0">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <ImageIcon className="h-4 w-4 text-primary" />
          Podgląd paragonu
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 p-0 overflow-hidden bg-black/5 relative flex items-center justify-center">
        {imageLoading ? (
          <div className="flex flex-col items-center gap-2 text-muted-foreground/40">
            <Loader2 className="h-8 w-8 animate-spin" />
            <p className="text-xs font-medium">Ładowanie obrazu...</p>
          </div>
        ) : imageUrl ? (
          <img
            src={imageUrl}
            alt="Receipt preview"
            className="max-w-full max-h-full object-contain z-10"
          />
        ) : (
          <div className="flex flex-col items-center justify-center text-muted-foreground/20">
            <ImageIcon className="h-24 w-24" />
            <p className="text-xs font-medium">Nie udało się załadować obrazu</p>
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
                <FileText className="h-4 w-4" /> Dane
              </TabsTrigger>
              <TabsTrigger value="receipt" className="flex items-center gap-2">
                <ImageIcon className="h-4 w-4" /> Paragon
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="form" className="flex-1 overflow-hidden m-0 p-0">
            {renderForm(true)}
          </TabsContent>
          <TabsContent value="receipt" className="flex-1 overflow-hidden m-0 p-0">
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
                  <CardTitle className="text-lg md:text-xl font-bold truncate">Weryfikacja danych</CardTitle>
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
                        <AlertDialogTitle>Czy na pewno odrzucić paragon?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Ta operacja całkowicie usunie transakcję i zdjęcie paragonu z systemu. Nie można tego cofnąć.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Anuluj</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => deleteMutation.mutate()}
                          className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        >
                          Odrzuć i usuń
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
                    <span className="hidden sm:inline">{isSubmitting ? "Zapis..." : "Zatwierdź"}</span>
                    <span className="sm:hidden">OK</span>
                  </Button>
                </div>
              </div>
            </CardHeader>

            <CardContent className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 custom-scrollbar">
              <div className="bg-muted/30 p-4 rounded-xl border border-border/50 space-y-4">
                <FormField
                  control={form.control}
                  name="merchant_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        <Store className="h-3 w-3" /> Sprzedawca
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
                          <CalendarIcon className="h-3 w-3" /> Data
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
                          <DollarSign className="h-3 w-3" /> Razem
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

              <div className="space-y-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-bold uppercase tracking-widest text-muted-foreground/70">Pozycje na paragonie</h3>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => append({ name: "", price: 0, quantity: 1 })}
                    className="h-8 text-xs gap-1 border-primary/20 hover:bg-primary/5 hover:text-primary transition-colors shrink-0"
                  >
                    <Plus className="h-3 w-3" /> Dodaj
                  </Button>
                </div>

                <div className="space-y-3">
                  {fields.map((field, index) => (
                    <div key={field.id} className="group relative bg-card border border-border/40 p-3 rounded-xl hover:border-primary/30 transition-all hover:shadow-sm">
                      <div className="flex flex-col gap-3">
                        <div className="flex gap-2">
                          <FormField
                            control={form.control}
                            name={`lines.${index}.name`}
                            render={({ field }) => (
                              <FormItem className="flex-1">
                                <FormControl>
                                  <Input {...field} placeholder="Nazwa pozycji..." className="h-9 text-sm bg-muted/20" />
                                </FormControl>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            onClick={() => remove(index)}
                            className="h-9 w-9 text-muted-foreground hover:text-destructive hover:bg-destructive/10 shrink-0"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>

                        <div className="grid grid-cols-12 gap-2">
                          <div className="col-span-4">
                            <FormField
                              control={form.control}
                              name={`lines.${index}.price`}
                              render={({ field }) => (
                                <FormItem>
                                  <FormControl>
                                    <div className="relative">
                                      <Input
                                        type="number"
                                        step="0.01"
                                        {...field}
                                        onChange={(e) => field.onChange(parseFloat(e.target.value) || 0)}
                                        className="h-9 text-sm bg-muted/20 pr-6"
                                        placeholder="Cena"
                                      />
                                      <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">zł</span>
                                    </div>
                                  </FormControl>
                                </FormItem>
                              )}
                            />
                          </div>
                          <div className="col-span-3">
                            <FormField
                              control={form.control}
                              name={`lines.${index}.quantity`}
                              render={({ field }) => (
                                <FormItem>
                                  <FormControl>
                                    <div className="relative">
                                      <Input
                                        type="number"
                                        step="0.01"
                                        {...field}
                                        onChange={(e) => field.onChange(parseFloat(e.target.value) || 0)}
                                        className="h-9 text-sm bg-muted/20 pr-5"
                                        placeholder="Ilość"
                                      />
                                      <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">szt</span>
                                    </div>
                                  </FormControl>
                                </FormItem>
                              )}
                            />
                          </div>
                          <div className="col-span-5">
                            <FormField
                              control={form.control}
                              name={`lines.${index}.category_id`}
                              render={({ field }) => (
                                <FormItem>
                                  <Select onValueChange={field.onChange} defaultValue={field.value}>
                                    <FormControl>
                                      <SelectTrigger className="h-9 text-xs bg-muted/20 px-2">
                                        <SelectValue placeholder="Kat." />
                                      </SelectTrigger>
                                    </FormControl>
                                    <SelectContent>
                                      {categories.map((cat) => (
                                        <SelectItem key={cat.id} value={cat.id.toString()}>
                                          <span className="flex items-center gap-2">
                                            <span>{cat.icon}</span>
                                            <span className="truncate max-w-[80px]">{cat.name}</span>
                                          </span>
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </FormItem>
                              )}
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>

            <CardFooter className="py-4 px-4 md:px-6 border-t bg-muted/30 shrink-0">
              <div className="flex flex-col sm:flex-row justify-between items-center w-full gap-2">
                <p className="text-[10px] md:text-xs text-muted-foreground flex items-center gap-2">
                  <AlertCircle className="h-3 w-3 shrink-0" /> Sprawdź zgodność z paragonem
                </p>
                <div className="text-xs md:text-sm font-bold">
                  Suma pozycji: {linesTotal.toFixed(2)} {form.getValues("currency")}
                </div>
              </div>
            </CardFooter>
          </form>
        </Form>
      </Card>
    );
  }
}
