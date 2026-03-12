import * as React from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

// Context so children automatically get open/onOpenChange from parent
interface CollapsibleContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const CollapsibleContext = React.createContext<CollapsibleContextValue>({
  open: false,
  onOpenChange: () => {}
});

interface CollapsibleProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  className?: string;
}

function Collapsible({
  open,
  onOpenChange,
  children,
  className
}: CollapsibleProps): React.ReactElement {
  const ctx = React.useMemo(
    () => ({ open, onOpenChange }),
    [open, onOpenChange]
  );
  return (
    <CollapsibleContext.Provider value={ctx}>
      <div className={cn("", className)}>{children}</div>
    </CollapsibleContext.Provider>
  );
}

interface CollapsibleTriggerProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
  className?: string;
}

function CollapsibleTrigger({
  open: openProp,
  onOpenChange: onOpenChangeProp,
  children,
  className
}: CollapsibleTriggerProps): React.ReactElement {
  const ctx = React.useContext(CollapsibleContext);
  const open = openProp ?? ctx.open;
  const onOpenChange = onOpenChangeProp ?? ctx.onOpenChange;

  return (
    <button
      onClick={() => onOpenChange(!open)}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs font-semibold hover:bg-accent transition-colors",
        className
      )}
    >
      <ChevronRight
        className={cn(
          "h-3.5 w-3.5 shrink-0 transition-transform duration-200",
          open && "rotate-90"
        )}
      />
      {children}
    </button>
  );
}

interface CollapsibleContentProps {
  open?: boolean;
  children: React.ReactNode;
  className?: string;
}

function CollapsibleContent({
  open: openProp,
  children,
  className
}: CollapsibleContentProps): React.ReactElement {
  const ctx = React.useContext(CollapsibleContext);
  const open = openProp ?? ctx.open;

  return (
    <div
      className={cn("", className)}
      style={open ? undefined : { display: "none" }}
    >
      {children}
    </div>
  );
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent };
