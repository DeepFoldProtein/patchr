import React from "react";
import { Button } from "./ui/button";
import { Home, Moon, Sun, Sparkles } from "lucide-react";
import { useAtom } from "jotai";
import { themeAtom } from "@/store/app-atoms";
import { useCurrentProject, useProjectStore } from "@/store/project-store";

export function Toolbar(): React.ReactElement {
  const [theme, setTheme] = useAtom(themeAtom);
  const currentProject = useCurrentProject();
  const clearProject = useProjectStore(state => state.clearProject);

  const toggleTheme = (): void => {
    const newTheme = theme === "dark" ? "light" : "dark";
    setTheme(newTheme);
    // Update title bar theme (macOS)
    if (window.api?.app?.setTheme) {
      void window.api.app.setTheme(newTheme);
    }
  };

  const handleHome = (): void => {
    clearProject();
  };

  return (
    <div className="flex h-14 items-center gap-3 border-b border-border/50 bg-background/80 backdrop-blur-xl px-6 shadow-sm safe-area-top">
      {/* Logo and Project Name */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-blue-500/30">
          <Sparkles className="h-4 w-4 text-blue-500 dark:text-blue-400" />
        </div>
        <div className="flex items-center gap-2">
          <div className="text-sm font-semibold text-slate-900 dark:text-white">
            {currentProject ? currentProject.name : "Patchr Studio"}
          </div>
          {currentProject && (
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-emerald-500/80" />
              <div className="text-xs text-slate-500 dark:text-slate-400">
                Active
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex-1" />

      {/* Action Buttons */}
      <Button
        variant="ghost"
        size="sm"
        onClick={handleHome}
        disabled={!currentProject}
        className="h-9 gap-2 text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100/50 dark:hover:bg-slate-800/50 disabled:opacity-40"
      >
        <Home className="h-4 w-4" />
        Home
      </Button>

      <div className="mx-1 h-6 w-px bg-slate-300/50 dark:bg-slate-800/50" />

      <Button
        variant="ghost"
        size="icon"
        onClick={toggleTheme}
        className="h-9 w-9 text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100/50 dark:hover:bg-slate-800/50"
      >
        {theme === "dark" ? (
          <Sun className="h-4 w-4" />
        ) : (
          <Moon className="h-4 w-4" />
        )}
      </Button>
    </div>
  );
}
