# Linting Rules and Fixes

This document outlines the linting rules enforced in the Patchr Studio project and the fixes applied to resolve linting errors.

## ESLint Configuration

The project uses ESLint with the following key configurations:

- `@electron-toolkit/eslint-config-ts` for TypeScript support
- `@electron-toolkit/eslint-config-prettier` for code formatting
- `eslint-plugin-react` for React-specific rules
- `eslint-plugin-react-hooks` for React hooks rules
- `eslint-plugin-react-refresh` for fast refresh compatibility

## Applied Fixes

### 1. Missing Return Type Annotations

**Rule**: `@typescript-eslint/explicit-function-return-type`

All React component functions and utility functions must have explicit return type annotations.

**Fixes Applied**:

- Added `React.ReactElement` return type to all React components
- Added appropriate return types to utility functions (e.g., `string` for `cn` function)
- Added `void` return type to event handlers

### 2. React Fast Refresh Compatibility

**Rule**: `react-refresh/only-export-components`

Files should only export React components to ensure fast refresh works properly.

**Fixes Applied**:

- Removed export of `buttonVariants` from `button.tsx` (utility constant)
- Added ESLint disable comments for hook exports in `ProjectProvider.tsx`

### 3. React Hooks Exhaustive Dependencies

**Rule**: `react-hooks/exhaustive-deps`

All dependencies used in `useMemo`, `useCallback`, etc. must be included in the dependency array.

**Fixes Applied**:

- Removed unnecessary `projectId` dependency from `useMemo` hooks in `ProjectProvider.tsx`

### 4. Code Formatting

**Rule**: `prettier/prettier`

Code must follow Prettier formatting rules.

**Fixes Applied**:

- Automatically fixed with `eslint --fix`
- Converted single quotes to double quotes
- Added semicolons where required
- Fixed indentation and spacing

## Running Linting

To check for linting errors:

```bash
npm run lint
```

To automatically fix fixable issues:

```bash
npm run lint -- --fix
```

## TypeScript Type Checking

In addition to ESLint, the project also runs TypeScript type checking:

```bash
npm run typecheck
```

This ensures type safety across the codebase.
