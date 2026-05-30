// Vitest setup — provides browser-like globals that jsdom + Node 22 don't
// ship by default.
//
// Why: Node 22 introduced experimental `localStorage` (gated behind
// `--localstorage-file`), and vitest 4's jsdom env does NOT install its own
// Storage shim — `localStorage` shows up as `undefined`, breaking every
// store/component test that touches persistence.
//
// Fix: install a minimal in-memory Storage implementation on `window` and
// re-export to `globalThis` so direct `localStorage.x` lookups also work.

class MemoryStorage implements Storage {
  private store = new Map<string, string>()
  get length(): number {
    return this.store.size
  }
  clear(): void {
    this.store.clear()
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }
  removeItem(key: string): void {
    this.store.delete(key)
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}

const localStorageShim = new MemoryStorage()
const sessionStorageShim = new MemoryStorage()

Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: localStorageShim,
})
Object.defineProperty(globalThis, 'sessionStorage', {
  configurable: true,
  value: sessionStorageShim,
})

if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: localStorageShim,
  })
  Object.defineProperty(window, 'sessionStorage', {
    configurable: true,
    value: sessionStorageShim,
  })
}
