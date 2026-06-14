import { X, CheckCircle, AlertCircle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Toast } from "@/store/toast";

interface ToastProps {
  toast: Toast;
  onClose: () => void;
}

const toastStyles = {
  success: {
    bg: "bg-green-500/10",
    border: "border-green-500/20",
    text: "text-green-600 dark:text-green-400",
    icon: CheckCircle,
  },
  error: {
    bg: "bg-destructive/10",
    border: "border-destructive/20",
    text: "text-destructive",
    icon: AlertCircle,
  },
  info: {
    bg: "bg-blue-500/10",
    border: "border-blue-500/20",
    text: "text-blue-600 dark:text-blue-400",
    icon: Info,
  },
};

export function ToastItem({ toast, onClose }: ToastProps) {
  const style = toastStyles[toast.type];
  const Icon = style.icon;

  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        "flex items-start gap-3 rounded-lg border p-4 shadow-lg",
        "animate-in slide-in-from-right-full duration-300",
        style.bg,
        style.border
      )}
    >
      <Icon className={cn("h-5 w-5 flex-shrink-0 mt-0.5", style.text)} />
      <p className={cn("flex-1 text-sm", style.text)}>{toast.message}</p>
      <button
        onClick={onClose}
        aria-label="Dismiss notification"
        className={cn(
          "flex-shrink-0 rounded-md p-1 opacity-70 transition-opacity",
          "hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          style.text
        )}
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
