import { Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import ProtectedRoute from "@/components/ProtectedRoute";
import LoginPage from "@/pages/Login";
import DashboardPage from "@/pages/Dashboard";
import ReviewsPage from "@/pages/Reviews";
import ReviewDetailPage from "@/pages/ReviewDetail";
import SettingsPage from "@/pages/Settings";
import RulesPage from "@/pages/Rules";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <Layout>
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/reviews" element={<ReviewsPage />} />
                <Route path="/reviews/:id" element={<ReviewDetailPage />} />
                <Route path="/rules" element={<RulesPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route
                  path="*"
                  element={
                    <div className="flex h-[60vh] flex-col items-center justify-center gap-2">
                      <h1 className="text-6xl font-bold text-muted-foreground">404</h1>
                      <p className="text-muted-foreground">Page not found</p>
                    </div>
                  }
                />
              </Routes>
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
