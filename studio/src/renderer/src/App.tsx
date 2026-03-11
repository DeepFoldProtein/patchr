import { useEffect, useRef } from "react";
import { Provider as JotaiProvider } from "jotai";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAtom } from "jotai";
import { themeClassAtom, themeAtom } from "@/store/app-atoms";
import { AppLayout } from "@/components/AppLayout";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { TooltipProvider } from "@/components/ui/tooltip";

// Create a client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      refetchOnWindowFocus: false
    }
  }
});

function AppContent(): React.JSX.Element {
  const [themeClass] = useAtom(themeClassAtom);
  const [theme] = useAtom(themeAtom);
  const molstarCSSLinkRef = useRef<HTMLLinkElement | null>(null);

  // Update title bar color when theme changes
  useEffect(() => {
    if (window.api?.app?.setTheme) {
      void window.api.app.setTheme(theme);
    }
  }, [theme]);

  useEffect(() => {
    if (themeClass) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [themeClass]);

  // Mol* CSS를 theme에 따라 동적으로 로드
  useEffect(() => {
    // 기존 Mol* CSS 제거
    if (molstarCSSLinkRef.current?.parentNode) {
      molstarCSSLinkRef.current.parentNode.removeChild(
        molstarCSSLinkRef.current
      );
      molstarCSSLinkRef.current = null;
    }

    // 새로운 theme의 Mol* CSS 로드
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = themeClass
      ? new URL("molstar/lib/mol-plugin-ui/skin/dark.scss", import.meta.url)
          .href
      : new URL("molstar/lib/mol-plugin-ui/skin/light.scss", import.meta.url)
          .href;

    document.head.appendChild(link);
    molstarCSSLinkRef.current = link;
  }, [themeClass]);

  return <AppLayout />;
}

function App(): React.JSX.Element {
  return (
    <ErrorBoundary>
      <JotaiProvider>
        <QueryClientProvider client={queryClient}>
          <TooltipProvider>
            <AppContent />
          </TooltipProvider>
        </QueryClientProvider>
      </JotaiProvider>
    </ErrorBoundary>
  );
}

export default App;
