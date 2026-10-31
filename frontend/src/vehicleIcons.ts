// Vehicle glyphs: 28x28 white silhouettes drawn on a state-coloured disc. Strings are static constants (no user data) so they are safe to inject as HTML.
import type { State } from './fleetGps'
import { STATE_COLOR } from './fleetGps'

const W = 'fill="#fff"', S = 'fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"', C = 'fill="currentColor" stroke="#fff" stroke-width="1.4"'
const wheel = (x: number, y: number, r = 2.1) => `<circle cx="${x}" cy="${y}" r="${r}" ${C}/>`
export const GLYPHS: Record<string, string> = {
  TWO_WHEELER: `<g ${S}><circle cx="7" cy="18" r="3"/><circle cx="21" cy="18" r="3"/><path d="M7 18 11 12h5l5 6M16 12l2-3h3M11 12 9 10H7"/></g>`,
  CAR: `<path d="M4.5 18v-4c0-.9.6-1.5 1.5-1.7L8.5 12l2-3h7l2.5 3 2 .3c.9.2 1.5.8 1.5 1.7v4z" ${W}/><path d="M11 9.9h2.6V12H9.7zM14.6 9.9h2.5l1.7 2.1h-4.2z" fill="currentColor"/>${wheel(9.5, 18)}${wheel(18.5, 18)}`,
  THREE_WHEELER: `<path d="M5 17V11.5C5 9.9 6 9 7.5 9H15c1.5 0 2.5.8 3 2l1 3h3.5v3z" ${W}/>${wheel(8.5, 18.5)}${wheel(14.5, 18.5)}${wheel(21.5, 18.5)}`,
  VAN: `<path d="M4 9.5h13V14h4.5l2.5 3.2V19H4z" ${W}/><path d="M18.5 14.8h2.6l1.4 1.9h-4z" fill="currentColor"/>${wheel(9, 19.5)}${wheel(19.5, 19.5)}`,
  BUS: `<rect x="4" y="7" width="20" height="13" rx="2.5" ${W}/><path d="M6 9.5h4v4H6zM12 9.5h4v4h-4zM18 9.5h4v4h-4z" fill="currentColor"/>${wheel(9, 20.2)}${wheel(19, 20.2)}`,
  TRUCK: `<rect x="3" y="8" width="13" height="10.5" rx="1" ${W}/><path d="M17.5 11h3.5l3.5 3.5v4h-7z" ${W}/>${wheel(8, 19.5)}${wheel(20, 19.5)}`,
  OTHER: `<path d="M14 6 21.5 14 14 22 6.5 14z" ${W}/><circle cx="14" cy="14" r="2.3" fill="currentColor"/>`,
}
export const glyph = (t: string) => GLYPHS[t] ?? GLYPHS.OTHER

/** Full map pin (32x32). selected = navy ring, critical = red badge, demo = dashed outline. */
export function markerHtml(type: string, state: State, o: { selected?: boolean; critical?: boolean; demo?: boolean } = {}) {
  const col = STATE_COLOR[state]
  return `<svg width="34" height="34" viewBox="0 0 32 32" style="color:${col};overflow:visible;filter:drop-shadow(0 1px 2px rgba(15,39,71,.45))">`
    + (o.selected ? '<circle cx="16" cy="16" r="15.5" fill="#fff" stroke="#0f2747" stroke-width="2.5"/>' : '')
    + `<circle cx="16" cy="16" r="13" fill="currentColor" stroke="#fff" stroke-width="2"${o.demo ? ' stroke-dasharray="3 2.5"' : ''}/>`
    + `<g transform="translate(2 2)">${glyph(type)}</g>`
    + (o.critical ? '<circle cx="27" cy="5" r="4.2" fill="#dc2626" stroke="#fff" stroke-width="1.6"/><path d="M27 3.2v2.2M27 6.4v.1" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/>' : '')
    + '</svg>'
}
/** Small inline icon for lists/panel. */
export const listIconHtml = (type: string, state: State) => `<svg width="28" height="28" viewBox="0 0 28 28" style="color:${STATE_COLOR[state]}"><circle cx="14" cy="14" r="14" fill="currentColor"/>${glyph(type)}</svg>`
