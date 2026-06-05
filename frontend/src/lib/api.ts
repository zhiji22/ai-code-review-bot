import axios from "axios";

/** Base axios instance pointing to FastAPI backend */
export const api = axios.create({
  baseURL: "/api/v1",
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

/** Attach JWT from localStorage on every request */
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/** Auto-refresh on 401 */
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    if (err.response?.status === 401 && !err.config._retry) {
      err.config._retry = true;
      const refreshToken = localStorage.getItem("refresh_token");
      if (refreshToken) {
        try {
          const { data } = await axios.post("/api/v1/auth/refresh", {
            refresh_token: refreshToken,
          });
          localStorage.setItem("access_token", data.data.access_token);
          localStorage.setItem("refresh_token", data.data.refresh_token);
          err.config.headers.Authorization = `Bearer ${data.data.access_token}`;
          return api(err.config);
        } catch {
          localStorage.removeItem("access_token");
          localStorage.removeItem("refresh_token");
          window.location.href = "/login";
        }
      } else {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  },
);

// ─── Types ──────────────────────────────────────────────────────────────────

export interface ApiResponse<T> {
  data: T;
  meta?: Record<string, unknown>;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  cursor?: string | null;
  next_cursor?: string | null;
}

export interface ReviewScores {
  overall: number;
  security: number;
  performance: number;
  maintainability: number;
}

export interface Review {
  id: number;
  repository_id: number;
  pr_number: number;
  commit_sha: string;
  pr_title: string;
  pr_author: string;
  status: string;
  overall_score: number;
  security_score: number;
  performance_score: number;
  maintainability_score: number;
  files_reviewed: number;
  files_total: number;
  lines_of_code: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  llm_model: string | null;
  llm_cost_usd: number;
  duration_ms: number;
  summary: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface ReviewComment {
  id: number;
  file_path: string;
  line_number: number;
  line_end: number | null;
  source: "rule" | "ast" | "llm";
  category: string;
  severity: "critical" | "warning" | "info";
  message: string;
  suggestion: string | null;
  rule_id: string | null;
  confidence: number;
}

export interface Repository {
  id: number;
  github_repo_id: number;
  full_name: string;
  owner: string;
  name: string;
  description: string | null;
  language: string | null;
  is_private: boolean;
  is_active: boolean;
  settings: RepoSettings;
  total_reviews: number;
  last_review_at: string | null;
  created_at: string;
}

export interface RepoSettings {
  auto_review: boolean;
  languages: string[];
  exclude_patterns: string[];
  severity_threshold: string;
  max_files_per_review: number;
  enable_llm: boolean;
  enable_ast: boolean;
  enable_rules: boolean;
  custom_rules_only: boolean;
}

export interface Rule {
  id: number;
  rule_id: string;
  name: string;
  description: string;
  category: "security" | "performance" | "style" | "best_practices";
  severity: "critical" | "warning" | "info";
  pattern: string;
  message: string;
  suggestion: string;
  languages: string[];
  enabled: boolean;
  is_builtin: boolean;
  repository_id: number | null;
  created_at: string;
}

export interface OverviewStats {
  total_reviews: number;
  total_repositories: number;
  total_issues: number;
  critical_issues: number;
  warning_issues: number;
  info_issues: number;
  avg_overall_score: number;
  avg_security_score: number;
  avg_performance_score: number;
  avg_maintainability_score: number;
  total_llm_cost_usd: number;
  total_llm_tokens: number;
  cache_hit_rate: number;
}

export interface TrendPoint {
  date: string;
  reviews: number;
  issues: number;
  critical: number;
  avg_score: number;
}

export interface CategoryBreakdown {
  category: string;
  critical: number;
  warning: number;
  info: number;
}

export interface User {
  id: number;
  username: string;
  email: string | null;
  avatar_url: string | null;
  name: string | null;
  is_admin: boolean;
}

// ─── API Functions ──────────────────────────────────────────────────────────

export const authApi = {
  devLogin: async () =>
    (await api.post<ApiResponse<{ access_token: string; refresh_token: string; user: User }>>("/auth/dev-login")).data.data,
  github: async (code: string) =>
    (await api.post<ApiResponse<{ access_token: string; refresh_token: string; user: User }>>("/auth/github", { code })).data.data,
  refresh: async (refresh_token: string) =>
    (await api.post<ApiResponse<{ access_token: string; refresh_token: string }>>("/auth/refresh", { refresh_token })).data.data,
  me: async () => (await api.get<ApiResponse<User>>("/auth/me")).data.data,
};

export const statsApi = {
  overview: async () => (await api.get<ApiResponse<OverviewStats>>("/stats/overview")).data.data,
  trends: async (days = 30) =>
    (await api.get<ApiResponse<{ points: TrendPoint[] }>>("/stats/trends", { params: { days } })).data.data,
  breakdown: async () => (await api.get<ApiResponse<CategoryBreakdown[]>>("/stats/breakdown")).data.data,
};

export const reviewsApi = {
  list: async (params?: {
    repository_id?: number;
    status?: string;
    cursor?: string;
    limit?: number;
  }) => (await api.get<ApiResponse<PaginatedResponse<Review>>>("/reviews", { params })).data.data,
  getById: async (id: number) => (await api.get<ApiResponse<Review>>(`/reviews/${id}`)).data.data,
  getComments: async (id: number) =>
    (await api.get<ApiResponse<ReviewComment[]>>(`/reviews/${id}/comments`)).data.data,
};

export const reposApi = {
  list: async () => (await api.get<ApiResponse<PaginatedResponse<Repository>>>("/repositories")).data.data,
  getById: async (id: number) => (await api.get<ApiResponse<Repository>>(`/repositories/${id}`)).data.data,
  update: async (id: number, data: Partial<Repository>) =>
    (await api.patch<ApiResponse<Repository>>(`/repositories/${id}`, data)).data.data,
  updateSettings: async (id: number, settings: Partial<RepoSettings>) =>
    (await api.put<ApiResponse<Repository>>(`/repositories/${id}/settings`, settings)).data.data,
  deactivate: async (id: number) => (await api.delete(`/repositories/${id}`)).data,
};

export const rulesApi = {
  list: async (params?: {
    category?: string;
    severity?: string;
    enabled?: boolean;
    is_builtin?: boolean;
  }) => (await api.get<ApiResponse<PaginatedResponse<Rule>>>("/rules", { params })).data.data,
  getById: async (id: number) => (await api.get<ApiResponse<Rule>>(`/rules/${id}`)).data.data,
  create: async (data: Partial<Rule>) => (await api.post<ApiResponse<Rule>>("/rules", data)).data.data,
  update: async (id: number, data: Partial<Rule>) =>
    (await api.patch<ApiResponse<Rule>>(`/rules/${id}`, data)).data.data,
  toggle: async (id: number) => (await api.post<ApiResponse<Rule>>(`/rules/${id}/toggle`)).data.data,
  delete: async (id: number) => (await api.delete(`/rules/${id}`)).data,
};
