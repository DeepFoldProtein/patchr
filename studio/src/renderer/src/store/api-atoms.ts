import { atom } from "jotai";

/** Base URL of the prediction / simulation server. */
export const apiUrlAtom = atom<string>("http://localhost:31212");

/** Connection status shared across all tabs. */
export const apiConnectionStatusAtom = atom<
  "idle" | "testing" | "connected" | "error"
>("idle");

/** Active panel tab — shared so child components can navigate. */
export type PanelMode = "project" | "repair" | "simulation";
export const panelModeAtom = atom<PanelMode>("repair");
