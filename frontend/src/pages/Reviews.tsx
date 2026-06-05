import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Spinner } from "@/components/ui/spinner";
import { reviewsApi } from "@/lib/api";
import { formatRelative, scoreColor } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";

export default function ReviewsPage() {
  const [cursor, setCursor] = useState<string | undefined>();
  const [offset, setOffset] = useState(0);

  const { data, isLoading } = useQuery({
    queryKey: ["reviews", cursor, offset],
    queryFn: () => reviewsApi.list({ cursor, limit: 20 }),
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
        <h1 className="text-3xl font-bold">Review History</h1>
        <p className="text-muted-foreground">All PR reviews across your repositories</p>
      </div>

      <Card>
        <CardHeader>
	          <CardTitle>Reviews ({data?.total ?? 0})</CardTitle>
        </CardHeader>
        <CardContent>
	          {!data?.items.length ? (
            <p className="py-8 text-center text-muted-foreground">No reviews yet</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>PR</TableHead>
                  <TableHead>Author</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Score</TableHead>
                  <TableHead>Issues</TableHead>
                  <TableHead>Files</TableHead>
                  <TableHead>Cost</TableHead>
                  <TableHead>When</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
	                {data?.items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      <Link to={`/reviews/${r.id}`} className="font-medium hover:underline">
                        #{r.pr_number} — {r.pr_title}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{r.pr_author}</TableCell>
                    <TableCell>
                      <Badge variant={r.status === "completed" ? "default" : "secondary"}>{r.status}</Badge>
                    </TableCell>
                    <TableCell>
                      <span className={`text-lg font-bold ${scoreColor(r.overall_score)}`}>
	                        {r.overall_score != null ? r.overall_score.toFixed(0) : "—"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1 text-xs">
                        {r.critical_count > 0 && (
                          <Badge variant="destructive">{r.critical_count}C</Badge>
                        )}
                        {r.warning_count > 0 && (
                          <Badge variant="secondary">{r.warning_count}W</Badge>
                        )}
                        {r.info_count > 0 && <Badge variant="outline">{r.info_count}I</Badge>}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {r.files_reviewed}/{r.files_total}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
	                      ${(r.llm_cost_usd ?? 0).toFixed(3)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatRelative(r.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {data?.next_cursor && (
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            size="sm"
            disabled={offset === 0}
            onClick={() => {
              setOffset(Math.max(0, offset - 20));
              setCursor(undefined);
            }}
          >
            <ChevronLeft className="h-4 w-4" /> Previous
          </Button>
          <span className="text-sm text-muted-foreground">
	            Showing {offset + 1}–{offset + (data?.items.length ?? 0)} of {data?.total}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setOffset(offset + 20);
	              setCursor(data.next_cursor ?? undefined);
            }}
          >
            Next <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
