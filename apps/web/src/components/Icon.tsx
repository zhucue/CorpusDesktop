import { paths } from "./iconPaths";
import { lucideIcons } from "./iconLucide";

export type IconName = keyof typeof paths | keyof typeof lucideIcons;

/** Every icon name: the mockup set first, then the lucide additions. */
export const ICON_NAMES = [...Object.keys(paths), ...Object.keys(lucideIcons).filter((k) => !(k in paths))] as IconName[];

/** Inline SVG icon: the design mockup set, otherwise a lucide icon. Decorative unless a label is given. */
export function Icon({ name, size, className, label }: { name: IconName; size?: 12 | 14 | 16 | 18 | 20; className?: string; label?: string }) {
  const cls = ["ic", size && size !== 16 ? `ic-${size}` : "", className ?? ""].filter(Boolean).join(" ");
  const a11y = { "aria-hidden": label ? undefined : true, role: label ? "img" : undefined, "aria-label": label } as const;
  if (name in paths)
    return (
      <svg
        className={cls}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        {...a11y}
        dangerouslySetInnerHTML={{ __html: paths[name as keyof typeof paths] }}
      />
    );
  const Lucide = lucideIcons[name as keyof typeof lucideIcons];
  return <Lucide className={cls} size={size ?? 16} strokeWidth={2} {...a11y} />;
}
