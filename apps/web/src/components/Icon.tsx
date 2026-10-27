import { paths } from "./iconPaths";

export type IconName = keyof typeof paths;

/** Inline SVG icon from the design mockups. Decorative unless a label is given. */
export function Icon({ name, size, className, label }: { name: IconName; size?: 12 | 14 | 16 | 18 | 20; className?: string; label?: string }) {
  const cls = ["ic", size && size !== 16 ? `ic-${size}` : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <svg
      className={cls}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
      dangerouslySetInnerHTML={{ __html: paths[name] }}
    />
  );
}
