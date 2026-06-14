import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Spinner } from "@/components/ui/spinner";
import { rulesApi, type Rule } from "@/lib/api";
import { severityColor } from "@/lib/utils";
import { Plus, Trash2, Power, Search } from "lucide-react";
import { useToastStore } from "@/store/toast";

export default function RulesPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["rules", filterCategory],
    queryFn: () => rulesApi.list({ category: filterCategory || undefined }),
  });

  const toggleMutation = useMutation({
    mutationFn: (id: number) => rulesApi.toggle(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      useToastStore.getState().addToast({
        type: "success",
        message: "Rule status updated",
      });
    },
    onError: (err: unknown) => {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      useToastStore.getState().addToast({
        type: "error",
        message: axiosErr.response?.data?.detail || "Failed to toggle rule",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => rulesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      useToastStore.getState().addToast({
        type: "success",
        message: "Rule deleted successfully",
      });
    },
    onError: (err: unknown) => {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      useToastStore.getState().addToast({
        type: "error",
        message: axiosErr.response?.data?.detail || "Failed to delete rule",
      });
    },
  });

  const filtered = (data?.items ?? []).filter((r) => {
    if (!search) return true;
    const s = search.toLowerCase();
    const ruleId = r.rule_id?.toLowerCase() ?? "";
    const name = r.name?.toLowerCase() ?? "";
    const description = r.description?.toLowerCase() ?? "";
    return (
      ruleId.includes(s) ||
      name.includes(s) ||
      description.includes(s)
    );
  });

  if (isLoading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Rule Management</h1>
          <p className="text-muted-foreground">Configure built-in and custom rules</p>
        </div>
        <Button onClick={() => setShowCreateForm(!showCreateForm)}>
          <Plus className="h-4 w-4" /> Custom Rule
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search rules..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value="">All Categories</option>
          <option value="security">Security</option>
          <option value="performance">Performance</option>
          <option value="style">Style</option>
          <option value="best_practices">Best Practices</option>
        </select>
      </div>

      {/* Create form */}
      {showCreateForm && (
        <CreateRuleForm onClose={() => setShowCreateForm(false)} />
      )}

      {/* Rules table */}
      <Card>
        <CardHeader>
          <CardTitle>Rules ({filtered.length})</CardTitle>
          <CardDescription>Built-in rules cannot be deleted, only toggled</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rule ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Languages</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((rule) => (
                <RuleRow
                  key={rule.id}
                  rule={rule}
                  onToggle={() => toggleMutation.mutate(rule.id)}
                  onDelete={() => deleteMutation.mutate(rule.id)}
                  isToggling={toggleMutation.isPending && toggleMutation.variables === rule.id}
                  isDeleting={deleteMutation.isPending && deleteMutation.variables === rule.id}
                />
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function RuleRow({
  rule,
  onToggle,
  onDelete,
  isToggling,
  isDeleting,
}: {
  rule: Rule;
  onToggle: () => void;
  onDelete: () => void;
  isToggling: boolean;
  isDeleting: boolean;
}) {
  return (
    <TableRow>
      <TableCell>
        <code className="text-xs">{rule.rule_id}</code>
        {!rule.is_builtin && <Badge variant="outline" className="ml-1 text-xs">custom</Badge>}
      </TableCell>
      <TableCell>
        <div>
          <p className="font-medium">{rule.name}</p>
          <p className="text-xs text-muted-foreground">{rule.description}</p>
        </div>
      </TableCell>
      <TableCell>
        <Badge variant="outline">{rule.category}</Badge>
      </TableCell>
      <TableCell>
        <Badge className={severityColor(rule.severity)}>{rule.severity}</Badge>
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {(rule.languages ?? []).join(", ")}
      </TableCell>
      <TableCell>
        <Badge variant={rule.enabled ? "default" : "secondary"}>
          {rule.enabled ? "Enabled" : "Disabled"}
        </Badge>
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button
            onClick={onToggle}
            variant="ghost"
            size="icon"
            loading={isToggling}
          >
            {isToggling ? null : <Power className="h-4 w-4" />}
          </Button>
          {!rule.is_builtin && (
            <Button
              onClick={onDelete}
              variant="ghost"
              size="icon"
              loading={isDeleting}
            >
              {isDeleting ? null : <Trash2 className="h-4 w-4 text-destructive" />}
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

function CreateRuleForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    rule_id: "",
    name: "",
    description: "",
    category: "security" as const,
    severity: "warning" as const,
    pattern: "",
    message: "",
    suggestion: "",
    languages: ["python"],
  });

  const createMutation = useMutation({
    mutationFn: () => rulesApi.create(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      useToastStore.getState().addToast({
        type: "success",
        message: "Rule created successfully",
      });
      onClose();
    },
    onError: (err: unknown) => {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      const message = axiosErr.response?.data?.detail
        || (err instanceof Error ? err.message : "Failed to create rule");
      useToastStore.getState().addToast({
        type: "error",
        message,
      });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create Custom Rule</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label className="text-sm font-medium">Rule ID</label>
            <Input
              placeholder="SEC101"
              value={form.rule_id}
              onChange={(e) => setForm({ ...form, rule_id: e.target.value })}
            />
          </div>
          <div>
            <label className="text-sm font-medium">Name</label>
            <Input
              placeholder="Rule name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
        </div>
        <div>
          <label className="text-sm font-medium">Description</label>
          <Input
            placeholder="What this rule checks"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label className="text-sm font-medium">Category</label>
            <select
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value as never })}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="security">Security</option>
              <option value="performance">Performance</option>
              <option value="style">Style</option>
              <option value="best_practices">Best Practices</option>
            </select>
          </div>
          <div>
            <label className="text-sm font-medium">Severity</label>
            <select
              value={form.severity}
              onChange={(e) => setForm({ ...form, severity: e.target.value as never })}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
          </div>
        </div>
        <div>
          <label className="text-sm font-medium">Pattern (Regex)</label>
          <Input
            placeholder="eval\\(|exec\\("
            value={form.pattern}
            onChange={(e) => setForm({ ...form, pattern: e.target.value })}
            className="font-mono"
          />
        </div>
        <div>
          <label className="text-sm font-medium">Message</label>
          <Input
            placeholder="Unsafe function usage detected"
            value={form.message}
            onChange={(e) => setForm({ ...form, message: e.target.value })}
          />
        </div>
        <div>
          <label className="text-sm font-medium">Suggestion</label>
          <Input
            placeholder="Consider using safer alternatives"
            value={form.suggestion}
            onChange={(e) => setForm({ ...form, suggestion: e.target.value })}
          />
        </div>
        <div>
          <label className="text-sm font-medium">Languages (comma-separated)</label>
          <Input
            placeholder="python, javascript, typescript"
            value={form.languages.join(", ")}
            onChange={(e) =>
              setForm({
                ...form,
                languages: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              })
            }
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => createMutation.mutate()}
            disabled={!form.rule_id || !form.pattern || createMutation.isPending}
          >
            {createMutation.isPending ? <Spinner /> : "Create Rule"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
