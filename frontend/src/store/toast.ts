import { create } from "zustand";

export interface Toast {
  id: string;
  type: "success" | "error" | "info";
  message: string;
  duration?: number;
}

interface ToastStore {
  toasts: Toast[];
  timeouts: Map<string, ReturnType<typeof setTimeout>>;
  addToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],
  timeouts: new Map(),
  addToast: (toast) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    const duration = toast.duration ?? 4000;

    const timeout = setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
        timeouts: new Map(state.timeouts).delete(id) ? state.timeouts : state.timeouts,
      }));
    }, duration);

    set((state) => {
      const newTimeouts = new Map(state.timeouts);
      newTimeouts.set(id, timeout);
      return {
        toasts: [...state.toasts, { ...toast, id }],
        timeouts: newTimeouts,
      };
    });
  },
  removeToast: (id) => {
    const timeout = get().timeouts.get(id);
    if (timeout) {
      clearTimeout(timeout);
    }
    set((state) => {
      const newTimeouts = new Map(state.timeouts);
      newTimeouts.delete(id);
      return {
        toasts: state.toasts.filter((t) => t.id !== id),
        timeouts: newTimeouts,
      };
    });
  },
}));
