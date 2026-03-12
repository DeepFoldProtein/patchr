import { useEffect } from "react";
import { Provider as JotaiProvider } from "jotai";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAtom } from "jotai";
import { themeClassAtom, themeAtom } from "@/store/app-atoms";
import { AppLayout } from "@/components/AppLayout";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { TooltipProvider } from "@/components/ui/tooltip";

// Import Mol* CSS at build time — both themes compiled into the bundle
import "molstar/lib/mol-plugin-ui/skin/dark.scss";

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
