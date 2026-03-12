import { atom } from "jotai";

const STORAGE_KEY = "patchr:apiUrl";

function loadApiUrl(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
  } catch {
    // ignore
  }
  return "http://localhost:31212";
}

/** Base URL of the prediction / simulation server (persisted to localStorage). */
const apiUrlBaseAtom = atom<string>(loadApiUrl());

export const apiUrlAtom = atom(
  get => get(apiUrlBaseAtom),
  (_get, set, value: string) => {
    set(apiUrlBaseAtom, value);
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // ignore
    }
  }
);

/** Connection status shared across all tabs. */
export const apiConnectionStatusAtom = atom<
  "idle" | "testing" | "connected" | "error"
>("idle");

/** Active panel tab — shared so child components can navigate. */
export type PanelMode = "project" | "repair" | "simulation";
export const panelModeAtom = atom<PanelMode>("repair");
