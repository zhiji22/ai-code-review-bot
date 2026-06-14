import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function Spinner({ className, ...props }: { className?: string } & React.HTMLAttributes<SVGElement>) {
  return <Loader2 className={cn("h-5 w-5 animate-spin text-muted-foreground", className)} {...props} />;
}

export function FullPageSpinner({ message }: { message?: string }) {
  return (
    <div className="flex h-[calc(100vh-4rem)] items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        {message && <p className="text-sm text-muted-foreground">{message}</p>}
      </div>
    </div>
  );
}
