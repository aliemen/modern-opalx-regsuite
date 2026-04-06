/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // All theme-sensitive colors use CSS variable channels so opacity
        // modifiers like bg-surface/50 work correctly in both light and dark.
        bg:      "rgb(var(--color-bg)      / <alpha-value>)",
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        border:  "rgb(var(--color-border)  / <alpha-value>)",
        muted:   "rgb(var(--color-muted)   / <alpha-value>)",
        accent:  "rgb(var(--color-accent)  / <alpha-value>)",
        fg:      "rgb(var(--color-fg)      / <alpha-value>)",
        // Status colors — absolute, readable on both light and dark backgrounds.
        passed:    "#22c55e",
        failed:    "#ef4444",
        broken:    "#f59e0b",
        cancelled: "#6b7280",
      },
    },
  },
  plugins: [],
};
