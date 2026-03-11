import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { logger } from "../lib/logger";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    logger.error("Uncaught error:", error, errorInfo);
  }

  public render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex h-full items-center justify-center bg-neutral-950">
          <div className="max-w-md rounded-lg border border-red-900/50 bg-red-950/20 p-6 text-center">
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-red-400" />
            <h2 className="mb-2 text-lg font-semibold text-red-400">
              Something went wrong
            </h2>
            <p className="mb-4 text-sm text-neutral-400">
              {this.state.error?.message || "An unexpected error occurred"}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="rounded-md bg-red-900/50 px-4 py-2 text-sm font-medium text-red-100 hover:bg-red-900/70 transition-colors"
            >
              Reload Application
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
