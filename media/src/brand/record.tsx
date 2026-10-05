// The motif: the record from the site's icon (pa-bailar-web frontend/src/pages/icons/[name].png.ts).
import React from "react";
import { C, FONT } from "../lib/tokens";

/**
 * Angle (degrees) of a record that starts turning at `startSec` and spins up to 33⅓ rpm (200°/s) over `ramp`
 * seconds, like a turntable's platter: easing in, never jumping to speed.
 */
export function spinAngle(tSec: number, startSec: number, ramp = 0.6): number {
  const x = Math.max(0, tSec - startSec);
  if (x < ramp) return 200 * (x - (ramp / 3) * (1 - (1 - x / ramp) ** 3));
  return 200 * (x - ramp / 3);
}

/**
 * Near-black disc, four faint grooves, marigold label (42% of the radius), wine spindle hole (10%). The label
 * carries a printed ring of text so the turn reads; a fixed sheen (it doesn't turn) sells the vinyl.
 */
export const Record: React.FC<{ size: number; angle: number; label?: string; style?: React.CSSProperties }> = ({
  size,
  angle,
  label = "PA' BAILAR · BOGOTÁ · SOCIALES · TALLERES ·",
  style,
}) => {
  const r = 250;
  return (
    <div style={{ width: size, height: size, ...style }}>
      <svg viewBox="0 0 512 512" width={size} height={size} style={{ overflow: "visible" }}>
        <defs>
          <path id="label-ring" d="M256,256 m-78,0 a78,78 0 1,1 156,0 a78,78 0 1,1 -156,0" />
          <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0.25" stopColor="#fff" stopOpacity="0" />
            <stop offset="0.42" stopColor="#fff" stopOpacity="0.12" />
            <stop offset="0.5" stopColor="#fff" stopOpacity="0" />
            <stop offset="0.58" stopColor="#fff" stopOpacity="0.08" />
            <stop offset="0.75" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <g transform={`rotate(${angle} 256 256)`}>
          <circle cx="256" cy="256" r={r} fill={C.wine950} />
          {[0.92, 0.82, 0.72, 0.62].map((k) => (
            <circle key={k} cx="256" cy="256" r={r * k} fill="none" stroke="#fff" strokeOpacity="0.07" strokeWidth="4" />
          ))}
          <circle cx="256" cy="256" r={r * 0.42} fill={C.marigold400} />
          <text fill={C.wine900} fontFamily={FONT.sans} fontWeight={600} fontSize="16">
            <textPath href="#label-ring" textLength={2 * Math.PI * 78 - 6} lengthAdjust="spacing">
              {label}
            </textPath>
          </text>
          <circle cx="256" cy="256" r={r * 0.1} fill={C.wine900} />
        </g>
        <circle cx="256" cy="256" r={r} fill="url(#sheen)" />
      </svg>
    </div>
  );
};
