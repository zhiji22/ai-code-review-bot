import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { authApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Bot, Github } from "lucide-react";

export default function LoginPage() {
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");

  const showDevLogin = import.meta.env.DEV;

  const handleDevLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await authApi.devLogin();
      setAuth(
        { access_token: result.access_token, refresh_token: result.refresh_token },
        {
          id: 1,
          username: "dev_user",
          email: "dev@test.com",
          avatar_url: null,
          name: "Dev User",
          is_admin: true,
        },
      );
      navigate("/");
    } catch {
      setError("Dev login failed. Is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  const handleGitHubLogin = () => {
    const clientId = import.meta.env.VITE_GITHUB_CLIENT_ID;
    if (!clientId) {
      setError("VITE_GITHUB_CLIENT_ID not configured. Use Dev Login instead.");
      return;
    }
    const redirectUri = window.location.origin + "/login";
    window.location.href = `https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${redirectUri}&scope=repo,user:email`;
  };

  const handleCodeSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await authApi.github(code.trim());
      setAuth(
        { access_token: result.access_token, refresh_token: result.refresh_token },
        result.user,
      );
      navigate("/");
    } catch {
      setError("Authentication failed. Please check your code.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-lg bg-primary">
            <Bot className="h-7 w-7 text-primary-foreground" />
          </div>
          <CardTitle className="text-2xl">AI Code Review Bot</CardTitle>
          <CardDescription>Sign in to get started</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {showDevLogin && (
            <Button onClick={handleDevLogin} className="w-full" size="lg" disabled={loading}>
              {loading ? <Spinner /> : "Dev Login (no GitHub required)"}
            </Button>
          )}

          <Button onClick={handleGitHubLogin} variant="outline" className="w-full" size="lg">
            <Github className="h-5 w-5" />
            Sign in with GitHub
          </Button>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-card px-2 text-muted-foreground">Or enter code manually</span>
            </div>
          </div>

          <form onSubmit={handleCodeSubmit} className="space-y-2">
            <Input
              placeholder="GitHub OAuth code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              disabled={loading}
            />
            <Button type="submit" className="w-full" disabled={loading || !code.trim()}>
              {loading ? <Spinner /> : "Sign In"}
            </Button>
          </form>

          {error && <p className="text-center text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>
    </div>
  );
}
