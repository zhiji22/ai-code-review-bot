import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { reposApi, type RepoSettings } from "@/lib/api";
import { Save, CheckCircle, XCircle } from "lucide-react";

const DEFAULT_SETTINGS: RepoSettings = {
  auto_review: true,
  languages: [],
  exclude_patterns: [],
  severity_threshold: "warning",
  max_files_per_review: 100,
  enable_llm: true,
  enable_ast: true,
  enable_rules: true,
  custom_rules_only: false,
};

export default function SettingsPage() {
  const { data: repos, isLoading } = useQuery({
    queryKey: ["repositories"],
    queryFn: reposApi.list,
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
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground">Manage repository configurations</p>
      </div>

            {!repos?.items.length ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">No repositories configured yet.</p>
            <p className="mt-2 text-sm text-muted-foreground">
              Install the GitHub App to start tracking repositories.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
                {repos?.items.map((repo) => (
            <RepoSettingCard key={repo.id} repo={repo} />
          ))}
        </div>
      )}
    </div>
  );
}

function RepoSettingCard({ repo }: { repo: Awaited<ReturnType<typeof reposApi.list>>["items"][number] }) {
  const queryClient = useQueryClient();
  const [settings, setSettings] = useState<RepoSettings>({ ...DEFAULT_SETTINGS, ...repo.settings });
  const [dirty, setDirty] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    setSettings({ ...DEFAULT_SETTINGS, ...repo.settings });
    setDirty(false);
  }, [repo.settings]);

  useEffect(() => {
    if (!feedback) return;
    const timer = setTimeout(() => setFeedback(null), 3000);
    return () => clearTimeout(timer);
  }, [feedback]);

  const updateMutation = useMutation({
    mutationFn: () => reposApi.updateSettings(repo.id, settings),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repositories"] });
      setDirty(false);
      setFeedback({ type: "success", message: "Settings saved successfully!" });
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : "Failed to save settings";
      setFeedback({ type: "error", message });
    },
  });

  const update = <K extends keyof RepoSettings>(key: K, value: RepoSettings[K]) => {
    setSettings({ ...settings, [key]: value });
    setDirty(true);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              {repo.full_name}
              {repo.is_private && <Badge variant="secondary">Private</Badge>}
              <Badge variant={repo.is_active ? "default" : "destructive"}>
                {repo.is_active ? "Active" : "Inactive"}
              </Badge>
            </CardTitle>
            <CardDescription>
              {repo.total_reviews} reviews • Language: {repo.language || "Multi"}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Toggles */}
        <div className="grid gap-3 md:grid-cols-2">
          <ToggleRow
            label="Auto Review"
            description="Automatically review new PRs"
            checked={settings.auto_review}
            onChange={(v) => update("auto_review", v)}
          />
          <ToggleRow
            label="Enable LLM"
            description="Use GPT-4o for deep analysis"
            checked={settings.enable_llm}
            onChange={(v) => update("enable_llm", v)}
          />
          <ToggleRow
            label="Enable AST"
            description="Structural code analysis"
            checked={settings.enable_ast}
            onChange={(v) => update("enable_ast", v)}
          />
          <ToggleRow
            label="Enable Rules"
            description="Pattern-based rule checks"
            checked={settings.enable_rules}
            onChange={(v) => update("enable_rules", v)}
          />
        </div>

        {/* Exclude patterns */}
        <div>
          <label className="text-sm font-medium">Exclude Patterns (comma-separated)</label>
          <Input
            placeholder="*.md, *.json, vendor/"
            value={settings.exclude_patterns.join(", ")}
            onChange={(e) =>
              update(
                "exclude_patterns",
                e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              )
            }
            className="mt-1"
          />
        </div>

        {/* Max files */}
        <div className="flex items-center gap-4">
          <label className="text-sm font-medium">Max Files per Review</label>
          <Input
            type="number"
            min={1}
            max={500}
            value={settings.max_files_per_review}
            onChange={(e) => update("max_files_per_review", Number(e.target.value))}
            className="w-32"
          />
        </div>

        <div className="flex items-center justify-end gap-2">
          {feedback && (
            <span
              className={`flex items-center gap-1 text-sm ${
                feedback.type === "success" ? "text-green-600" : "text-red-600"
              }`}
            >
              {feedback.type === "success" ? (
                <CheckCircle className="h-4 w-4" />
              ) : (
                <XCircle className="h-4 w-4" />
              )}
              {feedback.message}
            </span>
          )}
          <Button
            onClick={() => updateMutation.mutate()}
            disabled={!dirty || updateMutation.isPending}
          >
            {updateMutation.isPending ? <Spinner /> : <Save className="h-4 w-4" />}
            Save Changes
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between rounded-md border p-3 hover:bg-accent/50">
      <div>
        <p className="text-sm font-medium">{label}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-5 w-5 cursor-pointer rounded border-input accent-primary"
      />
    </label>
  );
}
