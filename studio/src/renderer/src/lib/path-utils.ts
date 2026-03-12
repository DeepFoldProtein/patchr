/**
 * Cross-platform path utilities for the renderer process.
 *
 * Paths from the main process use OS-native separators
 * (backslash on Windows, forward slash on macOS/Linux).
 * These helpers handle both separators correctly.
 */

const SEP_RE = /[\\/]/;
const SEP_RE_GLOBAL = /[\\/]/g;

/** Split a path into segments, handling both / and \ */
export function pathSplit(p: string): string[] {
  return p.split(SEP_RE).filter(Boolean);
}

/** Get the last segment (filename) from a path */
export function pathBasename(p: string): string {
  const parts = p.split(SEP_RE);
  return parts[parts.length - 1] || "";
}

/** Get the directory portion of a path */
export function pathDirname(p: string): string {
  const parts = p.split(SEP_RE);
  return parts.slice(0, -1).join("/");
}

/** Join path segments using forward slash (works on all OSes for IPC calls) */
export function pathJoin(...parts: string[]): string {
  return parts
    .map(p => p.replace(SEP_RE_GLOBAL, "/"))
    .join("/")
    .replace(/\/+/g, "/");
}

/** Check if a path contains a given sub-path segment pattern */
export function pathIncludes(p: string, segment: string): boolean {
  const normalized = p.replace(SEP_RE_GLOBAL, "/");
  return normalized.includes(segment);
}
