import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ground: "#EDF0F4",
        surface: "#FFFFFF",
        ink: "#0F1722",
        muted: "#5A6675",
        hairline: "#D2DAE3",
        active: "#12734F",
        superseded: "#64748B",
        disputed: "#A85B06",
        retracted: "#9B1B3C",
        ended: "#3F4C5D",
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
