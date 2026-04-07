import { useEffect, useState } from "react";

function readColor(name: string): string {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  // CSS variables are stored as space-separated RGB triplets, e.g. "15 23 42"
  return raw ? `rgb(${raw.replace(/ /g, ", ")})` : "rgb(128, 128, 128)";
}

function readAll() {
  return {
    fg: readColor("--color-fg"),
    muted: readColor("--color-muted"),
    border: readColor("--color-border"),
    surface: readColor("--color-surface"),
    accent: readColor("--color-accent"),
    bg: readColor("--color-bg"),
  };
}

/**
 * Reads the current CSS-variable theme colors as rgb() strings
 * suitable for Recharts SVG props. Re-reads on dark/light toggle.
 */
export function useThemeColors() {
  const [colors, setColors] = useState(readAll);

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setColors(readAll());
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  return colors;
}
