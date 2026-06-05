import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { statsApi, reviewsApi } from "@/lib/api";
import { formatNumber, formatCost, scoreColor } from "@/lib/utils";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { GitPullRequest, AlertOctagon, AlertTriangle, Info, DollarSign, Zap, TrendingUp } from "lucide-react";

const PIE_COLORS = ["#ef4444", "#f59e0b", "#3b82f6"];

export default function DashboardPage() {
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => setHydrated(true), []);

  const { data: overview, isLoading: ovLoading } = useQuery({
    queryKey: ["stats", "overview"],
    queryFn: statsApi.overview,
  });

  const { data: trends } = useQuery({
    queryKey: ["stats", "trends", 30],
    queryFn: () => statsApi.trends(30),
  });

  const { data: breakdown } = useQuery({
    queryKey: ["stats", "breakdown"],
    queryFn: statsApi.breakdown,
  });

  const { data: recentReviews } = useQuery({
    queryKey: ["reviews", "recent"],
    queryFn: () => reviewsApi.list({ limit: 5 }),
  });

  if (ovLoading || !overview || !hydrated) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  const trendData = (trends?.points ?? []).map((p) => ({
    date: p.date.slice(5),
    reviews: p.reviews,
    issues: p.issues,
    avg_score: Math.round(p.avg_score),
  }));

  const pieData = [
    { name: "Critical", value: overview.critical_issues },
    { name: "Warning", value: overview.warning_issues },
    { name: "Info", value: overview.info_issues },
  ];

  const categoryData = (breakdown ?? []).map((b) => ({
    category: b.category,
    critical: b.critical,
    warning: b.warning,
    info: b.info,
  }));

  const reviews = recentReviews?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Dashboard</h1>
        <p className="text-muted-foreground">Overview of your code review metrics</p>
      </div>

      {/* Stat cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<GitPullRequest className="h-5 w-5 text-blue-500" />}
          label="Total Reviews"
          value={formatNumber(overview.total_reviews)}
        />
        <StatCard
          icon={<AlertOctagon className="h-5 w-5 text-red-500" />}
          label="Critical Issues"
          value={formatNumber(overview.critical_issues)}
        />
        <StatCard
          icon={<TrendingUp className="h-5 w-5 text-green-500" />}
          label="Avg Score"
          value={`${(overview.avg_overall_score ?? 0).toFixed(1)}`}
          className={scoreColor(overview.avg_overall_score ?? 0)}
        />
        <StatCard
          icon={<DollarSign className="h-5 w-5 text-yellow-500" />}
          label="LLM Cost"
          value={formatCost(overview.total_llm_cost_usd)}
        />
      </div>

      {/* Secondary stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <AlertTriangle className="h-8 w-8 text-yellow-500" />
            <div>
              <p className="text-sm text-muted-foreground">Warning Issues</p>
              <p className="text-2xl font-bold">{formatNumber(overview.warning_issues)}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <Info className="h-8 w-8 text-blue-500" />
            <div>
              <p className="text-sm text-muted-foreground">Info Issues</p>
              <p className="text-2xl font-bold">{formatNumber(overview.info_issues)}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <Zap className="h-8 w-8 text-purple-500" />
            <div>
              <p className="text-sm text-muted-foreground">Cache Hit Rate</p>
              <p className="text-2xl font-bold">{((overview.cache_hit_rate ?? 0) * 100).toFixed(1)}%</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Review Trends (Last 30 Days)</CardTitle>
            <CardDescription>Daily reviews and issues detected</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "0.5rem",
                  }}
                />
                <Legend />
                <Line type="monotone" dataKey="reviews" stroke="#3b82f6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="issues" stroke="#ef4444" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Issue Severity Distribution</CardTitle>
            <CardDescription>Breakdown of all detected issues</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label>
                  {pieData.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Category breakdown */}
      {categoryData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Issues by Category</CardTitle>
            <CardDescription>Security, performance, style, and best practices</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={categoryData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="category" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                  }}
                />
                <Legend />
                <Bar dataKey="critical" stackId="a" fill="#ef4444" />
                <Bar dataKey="warning" stackId="a" fill="#f59e0b" />
                <Bar dataKey="info" stackId="a" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Recent reviews */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Reviews</CardTitle>
          <CardDescription>Latest 5 PR reviews</CardDescription>
        </CardHeader>
        <CardContent>
          {reviews.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">No reviews yet</p>
          ) : (
            <div className="space-y-2">
              {reviews.map((r) => (
                <div
                  key={r.id}
                  className="flex items-center justify-between rounded-md border p-3 hover:bg-accent/50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">PR #{r.pr_number} — {r.pr_title}</p>
                    <p className="text-xs text-muted-foreground">by {r.pr_author}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={r.status === "completed" ? "default" : "secondary"}>{r.status}</Badge>
                    <span className={`text-lg font-bold ${scoreColor(r.overall_score)}`}>
                      {r.overall_score != null ? r.overall_score.toFixed(0) : "—"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  className,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className={`text-2xl font-bold ${className ?? ""}`}>{value}</p>
          </div>
          {icon}
        </div>
      </CardContent>
    </Card>
  );
}
