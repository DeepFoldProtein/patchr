import { Color } from "molstar/lib/mol-util/color";

/** Mol* background colors matching Tailwind slate palette */
export const THEME_COLORS = {
  dark: Color.fromRgb(15, 23, 42), // slate-950
  light: Color.fromRgb(248, 250, 252) // slate-50
} as const;

/** Default API server URL */
export const DEFAULT_API_URL = "http://localhost:31212";

/** Max recent projects shown on welcome screen */
export const MAX_RECENT_PROJECTS = 10;
