/** JS-driven motion (count roll, typewriter, fly-to-basket) checks this; CSS handles the rest via @media. */
export function reducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
