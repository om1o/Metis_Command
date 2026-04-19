import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg0: "#07070b",
        bg1: "#0e0e14",
        bg2: "#15151d",
        surface: "#191922",
        border: "rgba(255,255,255,0.06)",
        text: "#e9e9ee",
        muted: "#8b8b98",
        amber: "#E8A446",
        cyan: "#4ECDC4",
        magenta: "#FF6B9D",
        purple: "#8B6CFF",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui"],
        serif: ['"Instrument Serif"', "Georgia", "serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        glow: "0 0 60px rgba(232,164,70,0.18)",
        card: "0 8px 28px rgba(0,0,0,0.35)",
      },
      animation: {
        aurora: "aurora 36s linear infinite",
        breath: "breath 2.4s ease-in-out infinite",
        fadeUp: "fadeUp .45s cubic-bezier(.2,.8,.2,1) both",
      },
      keyframes: {
        aurora: {
          "0%": { transform: "rotate(0deg) translate(0,0)" },
          "50%": { transform: "rotate(180deg) translate(2vw,-3vh)" },
          "100%": { transform: "rotate(360deg) translate(0,0)" },
        },
        breath: {
          "0%,100%": { transform: "scale(.85)", opacity: ".6" },
          "50%": { transform: "scale(1.15)", opacity: "1" },
        },
        fadeUp: {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
