import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, UserPlus } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { type BudgetMemberCreate } from "@/client";

const inviteSchema = z.object({
  email: z.string().email("Niepoprawny format email"),
  role: z.enum(["owner", "editor", "viewer"]),
});

type InviteFormValues = z.infer<typeof inviteSchema>;

export function BudgetTab() {
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);

  const form = useForm<InviteFormValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: {
      email: "",
      role: "editor",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: InviteFormValues) => api.inviteMember(values as BudgetMemberCreate),
    onSuccess: () => {
      toast.success("Użytkownik został zaproszony do budżetu");
      setIsInviteModalOpen(false);
      form.reset();
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const message = error.response?.data?.detail || "Błąd podczas zapraszania użytkownika";
      toast.error(message);
    },
  });

  const onSubmit = (values: InviteFormValues) => {
    mutation.mutate(values);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Zarządzaj budżetem</CardTitle>
          <CardDescription>
            Zaproś członków rodziny do wspólnego zarządzania domowym budżetem.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => setIsInviteModalOpen(true)}>
            <UserPlus className="mr-2 h-4 w-4" />
            Zaproś osobę
          </Button>
        </CardContent>
      </Card>

      <Dialog open={isInviteModalOpen} onOpenChange={setIsInviteModalOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Zaproś do budżetu</DialogTitle>
          </DialogHeader>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4 pt-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email użytkownika</FormLabel>
                    <FormControl>
                      <Input placeholder="np. zona@przyklad.pl" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Rola</FormLabel>
                    <Select onValueChange={field.onChange} defaultValue={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Wybierz rolę" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="owner">Właściciel</SelectItem>
                        <SelectItem value="editor">Edytor</SelectItem>
                        <SelectItem value="viewer">Widz</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <DialogFooter className="pt-4">
                <Button type="button" variant="outline" onClick={() => setIsInviteModalOpen(false)}>
                  Anuluj
                </Button>
                <Button type="submit" disabled={mutation.isPending}>
                  {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Zaproś
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
