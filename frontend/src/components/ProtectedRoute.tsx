import { useState, useEffect, ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/auth";
import { Spinner } from "@/components/ui/spinner";

/** Reactive hook: returns true once Zustand persist has finished rehydrating from localStorage. */
function useHasHydrated(): boolean {
  const [hydrated, setHydrated] = useState(() => useAuthStore.persist.hasHydrated());

  useEffect(() => {
    // If already hydrated (synchronous localStorage), skip subscription
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated(true);
      return;
    }
    // Otherwise, subscribe to hydration completion
    return useAuthStore.persist.onFinishHydration(() => setHydrated(true));
  }, []);

  return hydrated;
}

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const hasHydrated = useHasHydrated();

  // Wait for Zustand persist to rehydrate from localStorage before deciding.
  // Without this, isAuthenticated defaults to false on page refresh, causing a
  // premature redirect to /login even though valid tokens exist in localStorage.
  if (!hasHydrated) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
