import { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { LayoutDashboard, GitPullRequest, Settings, Shield, LogOut, Moon, Sun, Bot } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { useThemeStore } from "@/store/theme";
import { cn } from "@/lib/utils";
import { ToastContainer } from "@/components/ui/toast-container";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
}

const navItems: NavItem[] = [
  { to: "/", label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" /> },
  { to: "/reviews", label: "Reviews", icon: <GitPullRequest className="h-4 w-4" /> },
  { to: "/rules", label: "Rules", icon: <Shield className="h-4 w-4" /> },
  { to: "/settings", label: "Settings", icon: <Settings className="h-4 w-4" /> },
];

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const { user, logout } = useAuthStore();
  const { theme, toggle } = useThemeStore();

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="hidden w-60 flex-col border-r bg-card md:flex">
        <div className="flex h-14 items-center gap-2 border-b px-6">
          <Bot className="h-5 w-5 text-primary" />
          <span className="font-bold">AI Code Review</span>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {navItems.map((item) => {
            const active = location.pathname === item.to || location.pathname.startsWith(item.to + "/");
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                {item.icon}
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t p-3">
          {user && (
            <div className="mb-2 flex items-center gap-2 px-3 py-2">
              {user.avatar_url ? (
                <img src={user.avatar_url} alt={user.username} className="h-8 w-8 rounded-full" />
              ) : (
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-sm font-bold">
                  {user.username[0]?.toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{user.username}</p>
                <p className="truncate text-xs text-muted-foreground">{user.email || "No email"}</p>
              </div>
            </div>
          )}
          <div className="flex gap-1">
            <button
              onClick={toggle}
              className="flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-xs text-muted-foreground hover:bg-accent"
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              {theme === "dark" ? "Light" : "Dark"}
            </button>
            <button
              onClick={() => {
                logout();
                window.location.href = "/login";
              }}
              className="flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-xs text-muted-foreground hover:bg-accent"
            >
              <LogOut className="h-4 w-4" />
              Logout
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile header */}
      <div className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-2 border-b bg-card px-4 md:hidden">
        <Bot className="h-5 w-5 text-primary" />
        <span className="font-bold">AI Code Review</span>
        <div className="ml-auto flex gap-2">
          {navItems.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-md",
                location.pathname === item.to
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground",
              )}
            >
              {item.icon}
            </Link>
          ))}
        </div>
      </div>

      {/* Main content */}
      <main className="flex-1 overflow-auto pt-14 md:pt-0">
        <div className="container mx-auto max-w-7xl p-4 md:p-8">{children}</div>
      </main>

      {/* Toast Container - 固定在右下角 */}
      <ToastContainer />
    </div>
  );
}
