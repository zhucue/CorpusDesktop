import { useQuery } from "@tanstack/react-query";
import { Alert, Spin } from "antd";
import { Navigate, Route, Routes } from "react-router";
import { ApiError, api, errorText, type User } from "./api";
import Layout from "./Layout";
import Corpora from "./pages/Corpora";
import CorpusDetail from "./pages/CorpusDetail";
import Jobs from "./pages/Jobs";
import Login from "./pages/Login";
import Projects from "./pages/Projects";
import Search from "./search/Search";
import Settings from "./pages/Settings";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/auth/me"),
    retry: false,
    staleTime: Infinity,
  });
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const me = useMe();
  if (me.isPending) return <Spin style={{ display: "block", marginTop: 120 }} />;
  if (me.error instanceof ApiError && me.error.status === 401) return <Navigate to="/login" replace />;
  if (me.error) return <Alert type="error" showIcon message={errorText(me.error)} style={{ margin: 24 }} />;
  return <>{children}</>;
}

export default function App() {
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
        path="/p/:projectId"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="corpora" replace />} />
        <Route path="corpora" element={<Corpora />} />
        <Route path="corpora/:corpusId" element={<CorpusDetail />} />
        <Route path="search" element={<Search />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
