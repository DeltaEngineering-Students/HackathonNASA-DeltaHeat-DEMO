/**
 * Wash/mask strength k ∈ [0, 1] for a zone whose screen bbox is [x0, y0, x1, y1]: 1 while it intersects the viewport,
 * falling linearly to 0 at a distance of the viewport's longer side (board item 10: a binary in-view switch flashed
 * the whole map when the zone was dragged past the edge; a ramp over half a screen still brightened the map by ~8 % per
 * 40 px drag step — over a full screen it is ≤ ~3 %).
 */
export function spotFactor([x0, y0, x1, y1]: [number, number, number, number], w: number, h: number): number {
  const dx = Math.max(0, Math.min(x0, x1) - w, -Math.max(x0, x1));
  const dy = Math.max(0, Math.min(y0, y1) - h, -Math.max(y0, y1));
  const far = Math.max(w, h);
  return Math.max(0, Math.min(1, 1 - Math.hypot(dx, dy) / far));
}
