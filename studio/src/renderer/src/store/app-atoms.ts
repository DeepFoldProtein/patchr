import { atom } from "jotai";
import type { AppSession } from "../types";

// App-scope atoms (앱 전체에서 공유)
export const appSessionAtom = atom<AppSession>({
  port: 0,
  token: "",
  version: "0.1.0",
  backendReady: false
});

export const themeAtom = atom<"dark" | "light">("dark");

export const recentFilesAtom = atom<string[]>([]);

// Derived atom for theme class
export const themeClassAtom = atom(get => {
  const theme = get(themeAtom);
  return theme === "dark" ? "dark" : "";
});
