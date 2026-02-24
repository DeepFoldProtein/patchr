import { create } from "zustand";
import type { PreviewFrame } from "../types";

export interface PreviewState {
  isRunning: boolean;
  progress: number;
  elapsed_s: number;
  remaining_s: number;
  currentFrame: PreviewFrame | null;
  frames: PreviewFrame[];
  error: string | null;
  runId: string | null;
}

interface PreviewActions {
  startPreview: (
    runId: string,
    totalDuration: number,
    onComplete: (frames: PreviewFrame[]) => void
  ) => void;
  updateProgress: (
    elapsed: number,
    remaining: number,
    progress: number
  ) => void;
  addFrame: (frame: PreviewFrame) => void;
  completePreview: (frames?: PreviewFrame[]) => void;
  cancelPreview: () => void;
  setError: (error: string) => void;
  reset: () => void;
}

export type PreviewStore = PreviewState & PreviewActions;

const initialState: PreviewState = {
  isRunning: false,
  progress: 0,
  elapsed_s: 0,
  remaining_s: 0,
  currentFrame: null,
  frames: [],
  error: null,
  runId: null
};

// Global interval ID - lives outside React
let progressInterval: number | null = null;

export const usePreviewStore = create<PreviewStore>((set, get) => ({
  ...initialState,

  startPreview: (
    runId: string,
    totalDuration: number,
    onComplete: (frames: PreviewFrame[]) => void
  ) => {
    // Clear any existing interval
    if (progressInterval !== null) {
      clearInterval(progressInterval);
      progressInterval = null;
    }

    set({
      isRunning: true,
      progress: 0,
      elapsed_s: 0,
      remaining_s: totalDuration,
      currentFrame: null,
      frames: [],
      error: null,
      runId
    });

    // Start interval INSIDE the store - independent of React
    progressInterval = window.setInterval(() => {
      const state = get();
      const newElapsed = state.elapsed_s + 1;
      const newRemaining = Math.max(0, totalDuration - newElapsed);
      const newProgress = Math.min(100, (newElapsed / totalDuration) * 100);

      if (newElapsed >= totalDuration) {
        // Complete
        if (progressInterval !== null) {
          clearInterval(progressInterval);
          progressInterval = null;
        }

        // Call completion callback
        onComplete(state.frames);
      } else {
        // Update progress
        set({
          elapsed_s: newElapsed,
          remaining_s: newRemaining,
          progress: newProgress
        });
      }
    }, 1000);
  },

  updateProgress: (elapsed: number, remaining: number, progress: number) =>
    set({
      elapsed_s: elapsed,
      remaining_s: remaining,
      progress
    }),

  addFrame: (frame: PreviewFrame) =>
    set(state => ({
      frames: [...state.frames, frame],
      currentFrame: frame
    })),

  completePreview: (frames?: PreviewFrame[]) => {
    // Clear interval on completion
    if (progressInterval !== null) {
      clearInterval(progressInterval);
      progressInterval = null;
    }

    set(state => ({
      isRunning: false,
      progress: 100,
      remaining_s: 0,
      frames: frames || state.frames,
      currentFrame: frames?.[0] || state.currentFrame
    }));
  },

  cancelPreview: () => {
    // Clear interval on cancel
    if (progressInterval !== null) {
      clearInterval(progressInterval);
      progressInterval = null;
    }

    set(state => ({
      isRunning: false,
      progress: state.progress,
      elapsed_s: state.elapsed_s,
      remaining_s: 0
    }));
  },

  setError: (error: string) => {
    // Clear interval on error
    if (progressInterval !== null) {
      clearInterval(progressInterval);
      progressInterval = null;
    }

    set({
      isRunning: false,
      error
    });
  },

  reset: () => {
    // Clear interval on reset
    if (progressInterval !== null) {
      clearInterval(progressInterval);
      progressInterval = null;
    }

    set(initialState);
  }
}));
