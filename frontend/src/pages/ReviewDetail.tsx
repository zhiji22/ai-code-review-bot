import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { Button } from "@/components/ui/button";
import { reviewsApi } from "@/lib/api";
import { formatRelative, scoreColor, severityColor } from "@/lib/utils";
import { ArrowLeft, AlertOctagon, AlertTriangle, Info } from "lucide-react";

export default function ReviewDetailPage() {
  const { id } = useParams<{ id: string }>();
  const reviewId = Number(id);

  const { data: review, isLoading } = useQuery({
    queryKey: ["review", reviewId],
    queryFn: () => reviewsApi.getById(reviewId),
    enabled: !!reviewId,
    refetchInterval: (query) => {
      const data = query.state.data;
      const pending = data?.status !== "completed" && data?.status !== "failed";
      return pending ? 5_000 : false;
    },
  });

  const isInProgress = review?.status !== "completed" && review?.status !== "failed";

  const { data: comments } = useQuery({
    queryKey: ["review", reviewId, "comments"],
    queryFn: () => reviewsApi.getComments(reviewId),
    enabled: !!reviewId,
    refetchInterval: isInProgress ? 5_000 : false,
  });

  if (isLoading || !review) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  // Group comments by file
  const commentsByFile = (comments ?? []).reduce<Record<string, NonNullable<typeof comments>>>((acc, c) => {
    (acc[c.file_path] ??= []).push(c);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/reviews">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-5 w-5" />
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold">
            PR #{review.pr_number} — {review.pr_title}
          </h1>
          <p className="text-sm text-muted-foreground">
            by {review.pr_author} • {formatRelative(review.created_at)}
          </p>
        </div>
      </div>

      {/* Score cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <ScoreCard label="Overall" score={review.overall_score} highlight />
        <ScoreCard label="Security" score={review.security_score} />
        <ScoreCard label="Performance" score={review.performance_score} />
        <ScoreCard label="Maintainability" score={review.maintainability_score} />
      </div>

      {/* Summary */}
      {review.summary && (
        <Card>
          <CardHeader>
            <CardTitle>Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed">{review.summary}</p>
          </CardContent>
        </Card>
      )}

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <AlertOctagon className="h-8 w-8 text-red-500" />
            <div>
              <p className="text-sm text-muted-foreground">Critical</p>
              <p className="text-xl font-bold">{review.critical_count}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <AlertTriangle className="h-8 w-8 text-yellow-500" />
            <div>
              <p className="text-sm text-muted-foreground">Warning</p>
              <p className="text-xl font-bold">{review.warning_count}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <Info className="h-8 w-8 text-blue-500" />
            <div>
              <p className="text-sm text-muted-foreground">Info</p>
              <p className="text-xl font-bold">{review.info_count}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Comments by file */}
      <Card>
        <CardHeader>
          <CardTitle>Issues Found ({comments?.length ?? 0})</CardTitle>
          <CardDescription>Grouped by file and severity</CardDescription>
        </CardHeader>
        <CardContent>
          {Object.keys(commentsByFile).length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">No issues detected. Great code!</p>
          ) : (
            <div className="space-y-4">
              {Object.entries(commentsByFile).map(([file, fileComments]) => (
                <div key={file} className="rounded-md border">
                  <div className="border-b bg-muted/50 px-4 py-2">
                    <code className="text-sm font-mono">{file}</code>
                    <span className="ml-2 text-xs text-muted-foreground">
                      ({fileComments.length} issue{fileComments.length > 1 ? "s" : ""})
                    </span>
                  </div>
                  <div className="divide-y">
                    {fileComments
                      .sort((a, b) => {
                        const order = { critical: 0, warning: 1, info: 2 };
                        return order[a.severity] - order[b.severity];
                      })
                      .map((c) => (
                        <div key={c.id} className="flex gap-3 p-3">
                          <Badge className={`shrink-0 ${severityColor(c.severity)}`}>
                            {c.severity}
                          </Badge>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-muted-foreground">
                                L{c.line_number}
                                {c.line_end && c.line_end !== c.line_number && `–${c.line_end}`}
                              </span>
                              <Badge variant="outline" className="text-xs">
                                {c.source}
                              </Badge>
                              <Badge variant="outline" className="text-xs">
                                {c.category}
                              </Badge>
                              {c.rule_id && (
                                <code className="text-xs text-muted-foreground">{c.rule_id}</code>
                              )}
                            </div>
                            <p className="mt-1 text-sm">{c.message}</p>
                            {c.suggestion && (
                              <p className="mt-1 text-xs text-muted-foreground">
                                → {c.suggestion}
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
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

function ScoreCard({ label, score, highlight }: { label: string; score: number; highlight?: boolean }) {
  return (
    <Card className={highlight ? "ring-2 ring-primary" : ""}>
      <CardContent className="p-4 text-center">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className={`text-3xl font-bold ${scoreColor(score)}`}>{score.toFixed(0)}</p>
      </CardContent>
    </Card>
  );
}
