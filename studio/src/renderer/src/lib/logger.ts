/**
 * Lightweight logger that can be silenced in production.
 * In development (`import.meta.env.DEV`) all levels are active.
 * In production only `warn` and `error` are printed.
 */

const isDev = import.meta.env.DEV;

function noop(): void {
  /* intentionally empty */
}

export const logger = {
  /** Verbose information – stripped in production */
  debug: isDev ? console.debug.bind(console) : noop,
  /** General information – stripped in production */
  log: isDev ? console.log.bind(console) : noop,
  /** Warnings – always active */
  warn: console.warn.bind(console),
  /** Errors – always active */
  error: console.error.bind(console)
};
