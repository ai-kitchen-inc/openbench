/**
 * VoiceRecorder — inline recording bar with a live waveform (ChatGPT-style).
 *
 * The waveform is driven by a Web Audio AnalyserNode: each animation frame we
 * read the time-domain data, compute RMS amplitude, push it into a rolling
 * buffer, and draw vertical bars that grow with volume and scroll left.
 *
 * Monochrome, Lucide icons, no emojis (project design system).
 */

import { useEffect, useRef } from "react";

export interface VoiceRecorderProps {
  /** Live analyser node; null while tearing down. */
  analyser: AnalyserNode | null;
  /** "recording" → waveform live; "transcribing" → spinner, controls disabled. */
  state: "recording" | "transcribing";
  onCancel: () => void;
  onConfirm: () => void;
}

const BAR_COUNT = 48;

export function VoiceRecorder({ analyser, state, onCancel, onConfirm }: VoiceRecorderProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const levelsRef = useRef<number[]>(new Array(BAR_COUNT).fill(0));
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const data = analyser ? new Uint8Array(analyser.fftSize) : null;

    const draw = () => {
      rafRef.current = requestAnimationFrame(draw);

      // Compute the latest amplitude (RMS of the time-domain signal) and push
      // it onto the rolling buffer so bars "walk" left over time.
      let level = 0;
      if (analyser && data) {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) {
          const v = (data[i] ?? 128) - 128;
          sum += v * v;
        }
        level = Math.min(1, Math.sqrt(sum / data.length) / 64);
      }
      const levels = levelsRef.current;
      levels.push(level);
      if (levels.length > BAR_COUNT) levels.shift();

      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);
      const styles = getComputedStyle(canvas);
      ctx.fillStyle = styles.color || "#888";

      const rounded = ctx as CanvasRenderingContext2D & {
        roundRect?: (x: number, y: number, w: number, h: number, r: number) => void;
      };
      const slot = width / BAR_COUNT;
      const barW = Math.max(2, slot * 0.5);
      const mid = height / 2;
      for (let i = 0; i < levels.length; i += 1) {
        const lvl = levels[i] ?? 0;
        const h = Math.max(2, lvl * (height - 4));
        const x = i * slot + (slot - barW) / 2;
        const y = mid - h / 2;
        if (typeof rounded.roundRect === "function") {
          ctx.beginPath();
          rounded.roundRect(x, y, barW, h, barW / 2);
          ctx.fill();
        } else {
          ctx.fillRect(x, y, barW, h);
        }
      }
    };

    draw();
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [analyser]);

  return (
    <div className="chat-input__voice-bar" role="group" aria-label="Voice recording">
      <button
        className="chat-input__voice-cancel"
        onClick={onCancel}
        type="button"
        aria-label="Cancel voice input"
      >
        <svg
          aria-hidden="true"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>

      <canvas
        ref={canvasRef}
        className="chat-input__voice-canvas"
        width={640}
        height={36}
        aria-hidden="true"
      />

      {state === "transcribing" ? (
        <span className="chat-input__voice-spinner" aria-label="Transcribing" role="status">
          <svg
            aria-hidden="true"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
        </span>
      ) : (
        <button
          className="chat-input__voice-confirm"
          onClick={onConfirm}
          type="button"
          aria-label="Confirm voice input"
        >
          <svg
            aria-hidden="true"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </button>
      )}
    </div>
  );
}
