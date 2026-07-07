import { atom } from "jotai";

const STORAGE_KEY = "patchr:apiUrl";

/** Hosted default inference server (a 3090; ~1400-token capacity). */
export const DEFAULT_API_URL = "https://patchr-inference.deepfold.org";

/** Token budget of the default hosted server. Above this a bigger custom
 * server is required. */
export const DEFAULT_SERVER_TOKEN_LIMIT = 1400;

// The previous local default; migrate persisted copies of it to the hosted URL
// so existing installs pick up the hosted server too.
const LEGACY_DEFAULT = "http://localhost:31212";

function loadApiUrl(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && stored !== LEGACY_DEFAULT) return stored;
  } catch {
    // ignore
  }
  return DEFAULT_API_URL;
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
