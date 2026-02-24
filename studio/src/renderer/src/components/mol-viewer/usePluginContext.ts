// usePluginContext - Mol* PluginUIContext 초기화
import { useRef, useState, useCallback, useEffect } from "react";
import { useAtom } from "jotai";
import { themeClassAtom } from "@/store/app-atoms";
import { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import { createPluginUI } from "molstar/lib/mol-plugin-ui";
import { renderReact18 } from "molstar/lib/mol-plugin-ui/react18";
import { DefaultPluginUISpec } from "molstar/lib/mol-plugin-ui/spec";
import { Color } from "molstar/lib/mol-util/color";

export function usePluginContext(): {
  plugin: PluginUIContext | null;
  containerRef: React.RefCallback<HTMLDivElement>;
  error: string | null;
} {
  const [plugin, setPlugin] = useState<PluginUIContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDarkMode] = useAtom(themeClassAtom);
  const pluginInstanceRef = useRef<PluginUIContext | null>(null);
  const molstarRootRef = useRef<HTMLDivElement | null>(null);
  const containerNodeRef = useRef<HTMLDivElement | null>(null);
  const isDarkModeRef = useRef(isDarkMode);

  // isDarkMode 변경 감지하기 (ref로 저장)
  useEffect(() => {
    isDarkModeRef.current = isDarkMode;
  }, [isDarkMode]);

  // Theme 변경 감지 및 Mol* background color 업데이트
  useEffect(() => {
    if (!pluginInstanceRef.current) return;

    // Background color 변경
    const bgColor = isDarkMode
      ? Color.fromRgb(15, 23, 42) // slate-950 (dark)
      : Color.fromRgb(248, 250, 252); // slate-50 (light)

    if (pluginInstanceRef.current.canvas3d) {
      pluginInstanceRef.current.canvas3d.setProps({
        renderer: {
          backgroundColor: bgColor
        }
      });
    }

    console.log(`🎨 Theme changed to ${isDarkMode ? "dark" : "light"}`);
  }, [isDarkMode]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pluginInstanceRef.current) {
        console.log("🧹 Disposing Mol* viewer on unmount...");
        try {
          pluginInstanceRef.current.dispose();
        } catch (err) {
          console.debug("Plugin disposal error:", err);
        }
        pluginInstanceRef.current = null;
      }
      // Remove molstar root from DOM
      if (molstarRootRef.current && molstarRootRef.current.parentNode) {
        molstarRootRef.current.parentNode.removeChild(molstarRootRef.current);
        molstarRootRef.current = null;
      }
    };
  }, []);

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    containerNodeRef.current = node;

    if (!node) {
      return;
    }

    // Only initialize once
    if (pluginInstanceRef.current) {
      return;
    }

    const initPlugin = async (): Promise<void> => {
      try {
        console.log("🚀 Initializing Mol* viewer...");

        // Create a separate div that React won't touch
        const molstarRoot = document.createElement("div");
        molstarRoot.style.position = "absolute";
        molstarRoot.style.inset = "0";
        molstarRoot.style.width = "100%";
        molstarRoot.style.height = "100%";

        // Append directly to container
        node.appendChild(molstarRoot);
        molstarRootRef.current = molstarRoot;

        // Create custom spec - hide all UI panels, we'll render sequence separately
        const spec = DefaultPluginUISpec();
        spec.layout = {
          initial: {
            isExpanded: false,
            showControls: false, // Hide all built-in controls
            controlsDisplay: "reactive"
          }
        };

        spec.components = {
          ...spec.components,
          controls: {
            top: "none", // Hide sequence panel (we'll render it separately)
            left: "none",
            right: "none",
            bottom: "none"
          }
        };

        // Configure representation settings to exclude water by default
        if (spec.config) {
          spec.config = {
            ...spec.config
          };
        }

        // Initialize Mol* plugin
        const pluginUI = await createPluginUI({
          target: molstarRoot,
          render: renderReact18,
          spec
        });

        // 카메라 자동 회전 비활성화 및 배경색 설정
        const bgColor = isDarkModeRef.current
          ? Color.fromRgb(15, 23, 42) // slate-950 (dark)
          : Color.fromRgb(248, 250, 252); // slate-50 (light)

        if (pluginUI.canvas3d) {
          pluginUI.canvas3d.setProps({
            renderer: {
              backgroundColor: bgColor
            },
            trackball: {
              animate: {
                name: "off",
                params: {}
              }
            }
          });
        }

        pluginInstanceRef.current = pluginUI;
        console.log("✓ Mol* viewer initialized");
        setPlugin(pluginUI);
      } catch (err) {
        console.error("Failed to initialize Mol* viewer:", err);
        setError(err instanceof Error ? err.message : "Initialization failed");
      }
    };

    void initPlugin();
  }, []);

  return { plugin, containerRef, error };
}
