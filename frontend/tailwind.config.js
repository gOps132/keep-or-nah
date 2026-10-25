/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#0c0c0e",
        panel: "#141417",
        "panel-hover": "#1a1a1f",
        subtle: "#27272f",
        keep: {
          DEFAULT: "#16a34a",
          tint: "#bbf7d0",
        },
        nah: {
          DEFAULT: "#dc2626",
          tint: "#fecaca",
        },
        flag: {
          DEFAULT: "#d97706",
          tint: "#fde68a",
        },
        accent: {
          DEFAULT: "#3b82f6",
          hover: "#2563eb",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Text",
          "Segoe UI Variable",
          "Segoe UI",
          "Inter",
          "sans-serif",
        ],
        display: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Display",
          "Segoe UI Variable",
          "sans-serif",
        ],
        mono: ["SF Mono", "Cascadia Code", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
