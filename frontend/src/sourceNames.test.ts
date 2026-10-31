// @vitest-environment node
import { describe, it, expect } from 'vitest'

/* Windows and macOS ignore letter case in file names; Linux does not. `./Ask` must never be able to mean two files, or the app works in
   CI and on a Linux build but crashes on a developer's Windows machine ("does not provide an export named 'default'"). */
const files = Object.keys((import.meta as unknown as { glob: (p: string[]) => Record<string, unknown> }).glob(['/src/**/*.ts', '/src/**/*.tsx']))
  .filter(f => !/\.test\.tsx?$/.test(f) && !f.endsWith('.d.ts'))

describe('source file names', () => {
  it('finds the source tree (guard against a silently empty glob)', () => { expect(files.length).toBeGreaterThan(40) })
  it('no two modules share a name once letter case and extension are ignored', () => {
    const seen = new Map<string, string>(), clashes: string[] = []
    for (const f of files) { const key = f.replace(/\.tsx?$/, '').toLowerCase(); if (seen.has(key)) clashes.push(`${seen.get(key)} <-> ${f}`); else seen.set(key, f) }
    expect(clashes).toEqual([])
  })
})
