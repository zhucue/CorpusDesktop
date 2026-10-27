import { Alert, Spin } from "antd";
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";
import { ApiError, errorText } from "./api";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import AppShell from "./components/shell/AppShell";
import Login from "./features/auth/Login";
import Projects from "./features/projects/Projects";
import { useMe } from "./lib/data";

const Corpora = lazy(() => import("./features/corpora/Corpora"));
const Search = lazy(() => import("./features/search/Search"));
const Stats = lazy(() => import("./features/stats/Stats"));
const Annotate = lazy(() => import("./features/annotate/Annotate"));
const Assistant = lazy(() => import("./features/assistant/AssistantPage"));
const Jobs = lazy(() => import("./features/jobs/Jobs"));
const Settings = lazy(() => import("./features/settings/Settings"));
const Onboarding = lazy(() => import("./features/onboarding/Onboarding"));

export { useMe };

function RequireAuth({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const loc = useLocation();
  if (me.isPending) return <Spin style={{ display: "block", marginTop: 120 }} />;
  if (me.error instanceof ApiError && me.error.status === 401)
    return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (me.error) return <Alert type="error" showIcon message={errorText(me.error)} style={{ margin: 24 }} />;
  return <>{children}</>;
}

const Fallback = <Spin style={{ display: "block", marginTop: 120 }} />;

export default function App() {
  const { pathname } = useLocation();
  // Login, project list and onboarding reset per path; pages in the shell have their own boundary around the Outlet.
  return (
    <ErrorBoundary key={pathname.startsWith("/p/") ? "shell" : pathname}>
      <AppRoutes />
    </ErrorBoundary>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Projects />
          </RequireAuth>
        }
      />
      <Route
        path="/onboarding"
        element={
          <RequireAuth>
            <Suspense fallback={Fallback}>
              <Onboarding />
            </Suspense>
          </RequireAuth>
        }
      />
      <Route
        path="/p/:projectId"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="corpora" replace />} />
        <Route path="corpora" element={<Corpora />} />
        <Route path="corpora/:corpusId" element={<Corpora />} />
        <Route path="search" element={<Search />} />
        <Route path="stats" element={<Stats />} />
        <Route path="annotate" element={<Annotate />} />
        <Route path="assistant" element={<Assistant />} />
        <Route path="assistant/:sessionId" element={<Assistant />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
