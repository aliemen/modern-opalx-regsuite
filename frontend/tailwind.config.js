/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#020617",
        surface: "#0f172a",
        border: "#1e293b",
        muted: "#9ca3af",
        accent: "#38bdf8",
        passed: "#22c55e",
        failed: "#ef4444",
        broken: "#f59e0b",
        cancelled: "#6b7280",
      },
    },
  },
  plugins: [],
};

