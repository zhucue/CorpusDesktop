import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./theme/tokens.css";
import "./theme/app.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { ApiError } from "./api";
import App from "./App";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { antdTheme } from "./theme/antd";
import { ThemeProvider } from "./theme/theme";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (count, e) => !(e instanceof ApiError && e.status < 500) && count < 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Router outermost: antd message/notification holders render <Link> in their content. */}
    <BrowserRouter>
      <ThemeProvider>
        {(mode) => (
          <ConfigProvider locale={zhCN} theme={antdTheme(mode)}>
            <AntApp message={{ maxCount: 3 }}>
              <QueryClientProvider client={queryClient}>
                <ErrorBoundary>
                  <App />
                </ErrorBoundary>
              </QueryClientProvider>
            </AntApp>
          </ConfigProvider>
        )}
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
);
