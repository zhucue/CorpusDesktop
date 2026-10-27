import type { AnnotStatus } from "../../api";

/** A word-alignment group as stored (contracts/p5.md alignment_annotations): src × tgt, 1-based token numbers. */
export interface LinkGroup {
  id: string;
  src: number[];
  tgt: number[];
  status: AnnotStatus;
}

export type LinkOp = { op: "create"; src: number[]; tgt: number[] } | { op: "modify"; id: string; src: number[]; tgt: number[] } | { op: "reject"; id: string };

const live = (g: LinkGroup) => g.status !== "rejected";
const without = (xs: number[], x: number) => xs.filter((v) => v !== x);
const sorted = (xs: number[]) => [...new Set(xs)].sort((a, b) => a - b);

/** Whether src token i and tgt token j are linked by a group that is not rejected. */
export function linked(groups: LinkGroup[], i: number, j: number): boolean {
  return groups.some((g) => live(g) && g.src.includes(i) && g.tgt.includes(j));
}

/**
 * Toggle the link between src token i and tgt token j, as the API operations that do it plus the groups afterwards.
 * Remove: a 1:1 group is rejected; otherwise the group drops i (one target) or j (one source); a many-to-many
 * group drops i and the rest of i's links move to a new group. Add: joins a group whose only source is i
 * (or whose only target is j), else a new 1:1 group. New groups get temporary ids `tmp:<n>`.
 */
export function toggleLink(groups: LinkGroup[], i: number, j: number): { ops: LinkOp[]; next: LinkGroup[] } {
  const ops: LinkOp[] = [];
  let next = groups.map((g) => ({ ...g }));
  let tmp = 0;
  const create = (src: number[], tgt: number[]) => {
    ops.push({ op: "create", src, tgt });
    next.push({ id: `tmp:${tmp++}`, src, tgt, status: "confirmed" });
  };
  const modify = (g: LinkGroup, src: number[], tgt: number[]) => {
    ops.push({ op: "modify", id: g.id, src, tgt });
    next = next.map((x) => (x.id === g.id ? { ...x, src, tgt, status: "modified" } : x));
  };

  const hit = groups.find((g) => live(g) && g.src.includes(i) && g.tgt.includes(j));
  if (hit) {
    if (hit.src.length === 1 && hit.tgt.length === 1) {
      ops.push({ op: "reject", id: hit.id });
      next = next.map((x) => (x.id === hit.id ? { ...x, status: "rejected" } : x));
    } else if (hit.src.length === 1) modify(hit, hit.src, without(hit.tgt, j));
    else if (hit.tgt.length === 1) modify(hit, without(hit.src, i), hit.tgt);
    else {
      modify(hit, without(hit.src, i), hit.tgt);
      create([i], without(hit.tgt, j));
    }
    return { ops, next };
  }
  const bySrc = groups.find((g) => live(g) && g.src.length === 1 && g.src[0] === i);
  if (bySrc) {
    modify(bySrc, bySrc.src, sorted([...bySrc.tgt, j]));
    return { ops, next };
  }
  const byTgt = groups.find((g) => live(g) && g.tgt.length === 1 && g.tgt[0] === j);
  if (byTgt) {
    modify(byTgt, sorted([...byTgt.src, i]), byTgt.tgt);
    return { ops, next };
  }
  create([i], [j]);
  return { ops, next };
}
