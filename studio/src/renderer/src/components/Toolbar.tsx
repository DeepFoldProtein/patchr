import React from "react";
import { Button } from "./ui/button";
import { Home, Moon, Sun } from "lucide-react";
import logoIcon from "@/assets/logo.png";
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
        <div className="relative w-8 h-8 rounded-lg overflow-hidden shadow-lg">
          <img src={logoIcon} alt="Patchr" className="w-full h-full" />
          <div className="absolute inset-0 bg-gradient-to-b from-white/30 via-transparent to-transparent" />
          <div className="absolute inset-0 rounded-lg ring-1 ring-inset ring-white/20" />
        </div>
        <div className="flex items-center gap-2">
          <div className="text-sm font-semibold text-neutral-900 dark:text-white">
            {currentProject ? currentProject.name : "Patchr Studio"}
          </div>
          {currentProject && (
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-neutral-400 dark:bg-neutral-500" />
              <div className="text-xs text-neutral-500 dark:text-neutral-400">
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
        className="h-9 gap-2 text-neutral-700 dark:text-neutral-300 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-100/50 dark:hover:bg-neutral-800/50 disabled:opacity-40"
      >
        <Home className="h-4 w-4" />
        Home
      </Button>

      <div className="mx-1 h-6 w-px bg-neutral-300/50 dark:bg-neutral-800/50" />

      <Button
        variant="ghost"
        size="icon"
        onClick={toggleTheme}
        className="h-9 w-9 text-neutral-700 dark:text-neutral-300 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-100/50 dark:hover:bg-neutral-800/50"
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
