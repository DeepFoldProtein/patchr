import { useEffect, useCallback, useRef } from "react";
import { useAtom } from "jotai";
import type { PluginContext } from "molstar/lib/mol-plugin/context";
import { previewStateAtom } from "../../store/mol-viewer-atoms";
import { bus } from "../../lib/event-bus";
import type { PreviewFrame, InpaintParams, PreviewState } from "../../types";

/**
 * Manage Boltz-Inpainting preview stream
 *
 * Features:
 * - WebSocket-based streaming with time-based progress
 * - Binary frame parsing (256B header + PDB data)
 * - Multi-seed result handling
 * - Automatic reconnection on error
 */
export function usePreviewManager(plugin: PluginContext | null): {
  startPreview: (params: InpaintParams) => Promise<void>;
  cancelPreview: () => void;
  clearFrames: () => void;
  previewState: PreviewState;
} {
  const [previewState, setPreviewState] = useAtom(previewStateAtom);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 3;

  /**
   * Parse binary frame from server
   * Frame format: 256-byte header + PDB data
   * Header: [frameIndex(4), totalFrames(4), confidence(4), temperature(4), plddt_mean(4), ...]
   */
  const parseFrame = useCallback((buffer: ArrayBuffer): PreviewFrame | null => {
    try {
      if (buffer.byteLength < 256) {
        console.warn("Frame too small:", buffer.byteLength);
        return null;
      }

      const header = new DataView(buffer, 0, 256);
      const frameIndex = header.getUint32(0, true);
      const totalFrames = header.getUint32(4, true);
      const confidence = header.getFloat32(8, true);
      const temperature = header.getFloat32(12, true);
      const plddt_mean = header.getFloat32(16, true);

      const structureData = buffer.slice(256);

      const frame: PreviewFrame = {
        frameId: `frame-${frameIndex}`,
        frameIndex,
        totalFrames,
        structure: structureData,
        confidence,
        temperature,
        plddt_mean: isNaN(plddt_mean) ? undefined : plddt_mean,
        timestamp: Date.now()
      };

      return frame;
    } catch (error) {
      console.error("Failed to parse frame:", error);
      return null;
    }
  }, []);

  /**
   * Handle JSON messages from server (progress, start, complete, error)
   */
  const handleMessage = useCallback(
    (msg: {
      type: string;
      run_id?: string;
      estimated_duration_s?: number;
      elapsed_s?: number;
      remaining_s?: number;
      progress_percent?: number;
      frames_count?: number;
      plddt_scores?: number[];
      error_message?: string;
      error_code?: string;
    }) => {
      switch (msg.type) {
        case "start":
          setPreviewState(prev => ({
            ...prev,
            isRunning: true,
            runId: msg.run_id ?? null,
            frames: [],
            error: null,
            elapsed_s: 0,
            remaining_s: msg.estimated_duration_s ?? 0,
            progress: 0
          }));
          bus.emit("preview:started", { runId: msg.run_id ?? "unknown" });
          break;

        case "progress":
          setPreviewState(prev => ({
            ...prev,
            elapsed_s: msg.elapsed_s ?? 0,
            remaining_s: msg.remaining_s ?? 0,
            progress: msg.progress_percent ?? 0
          }));
          bus.emit("preview:progress", {
            progress: msg.progress_percent ?? 0,
            elapsed_s: msg.elapsed_s ?? 0,
            remaining_s: msg.remaining_s ?? 0
          });
          break;

        case "complete":
          setPreviewState(prev => ({
            ...prev,
            isRunning: false,
            progress: 100,
            remaining_s: 0
          }));
          bus.emit("preview:complete", {
            totalFrames: msg.frames_count ?? 0,
            plddt_scores: msg.plddt_scores
          });
          break;

        case "error":
          setPreviewState(prev => ({
            ...prev,
            isRunning: false,
            error: msg.error_message ?? "Unknown error"
          }));
          bus.emit("preview:error", {
            error: msg.error_message ?? "Unknown error",
            code: msg.error_code
          });
          break;

        default:
          console.warn("Unknown message type:", msg.type);
      }
    },
    [setPreviewState]
  );

  /**
   * Handle binary frame data
   */
  const handleFrameData = useCallback(
    (data: ArrayBuffer) => {
      const frame = parseFrame(data);
      if (frame) {
        setPreviewState(prev => ({
          ...prev,
          currentFrame: frame,
          frames: [...prev.frames, frame]
        }));

        bus.emit("preview:frameUpdated", frame);

        // TODO: Load structure into Mol* viewer
        if (plugin) {
          console.log(
            `Frame ${frame.frameIndex + 1}/${frame.totalFrames} received (pLDDT: ${frame.plddt_mean?.toFixed(1)})`
          );
        }
      }
    },
    [parseFrame, plugin, setPreviewState]
  );

  /**
   * Start preview stream
   */
  const startPreview = useCallback(
    async (params: InpaintParams): Promise<void> => {
      if (!plugin) {
        console.warn("Plugin not initialized");
        return;
      }

      // Close existing connection
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }

      try {
        // Reset reconnect attempts
        reconnectAttemptsRef.current = 0;

        const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${wsProtocol}//localhost:8000/api/inpaint/preview`);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("Preview WebSocket connected");

          // Send request
          ws.send(
            JSON.stringify({
              project_id: "current-project",
              seeds: params.seeds,
              temperature: params.temperature,
              confidence_threshold: params.confidence_threshold,
              mask: {
                /* TODO: get from mask atom */
              }
            })
          );

          // Initialize state
          setPreviewState({
            isRunning: true,
            progress: 0,
            elapsed_s: 0,
            remaining_s: 0,
            currentFrame: null,
            frames: [],
            error: null,
            runId: null
          });
        };

        ws.onmessage = event => {
          if (typeof event.data === "string") {
            // JSON message
            try {
              const msg = JSON.parse(event.data);
              handleMessage(msg);
            } catch (err) {
              console.error("Failed to parse JSON message:", err);
            }
          } else if (event.data instanceof ArrayBuffer) {
            // Binary frame
            handleFrameData(event.data);
          }
        };

        ws.onerror = error => {
          console.error("WebSocket error:", error);

          // Retry connection immediately (no delay)
          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttemptsRef.current++;

            console.log(
              `Reconnecting immediately (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`
            );

            // Use requestAnimationFrame for non-blocking immediate retry
            requestAnimationFrame(() => {
              startPreview(params);
            });
          } else {
            setPreviewState(prev => ({
              ...prev,
              isRunning: false,
              error: "Connection failed after multiple attempts"
            }));
          }
        };

        ws.onclose = () => {
          console.log("Preview WebSocket closed");
          setPreviewState(prev => ({
            ...prev,
            isRunning: false
          }));
        };
      } catch (error) {
        console.error("Failed to start preview:", error);
        setPreviewState(prev => ({
          ...prev,
          isRunning: false,
          error: String(error)
        }));
      }
    },
    [plugin, setPreviewState, handleMessage, handleFrameData]
  );

  /**
   * Cancel preview stream
   */
  const cancelPreview = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setPreviewState(prev => ({
      ...prev,
      isRunning: false
    }));

    bus.emit("preview:cancelled");
  }, [setPreviewState]);

  /**
   * Clear all frames and reset state
   */
  const clearFrames = useCallback(() => {
    setPreviewState({
      isRunning: false,
      progress: 0,
      elapsed_s: 0,
      remaining_s: 0,
      currentFrame: null,
      frames: [],
      error: null,
      runId: null
    });
  }, [setPreviewState]);

  /**
   * Cleanup on unmount
   */
  useEffect(() => {
    return () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    };
  }, []);

  return { startPreview, cancelPreview, clearFrames, previewState };
}
