#!/usr/bin/env node
/**
 * OpenAPI -> TypeScript codegen for the SPA.
 *
 * Reads OPENAPI_URL (default http://localhost:8000/openapi.json) and writes
 * `web/src/api/generated/api.ts` using openapi-typescript.
 *
 * Flags:
 *   --if-server-up  Do not fail if the API isn't reachable. If a previously
 *                   generated file already exists, leave it. Otherwise emit
 *                   a tiny stub so downstream `tsc` builds still pass.
 *
 * Usage:
 *   node scripts/gen-api-types.mjs               # strict (default)
 *   node scripts/gen-api-types.mjs --if-server-up
 *   OPENAPI_URL=https://api.example.com/openapi.json node scripts/gen-api-types.mjs
 */

import { existsSync, mkdirSync, writeFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT_FILE = resolve(__dirname, "../src/api/generated/api.ts")
const OPENAPI_URL = process.env.OPENAPI_URL ?? "http://localhost:8000/openapi.json"
const SOFT = process.argv.includes("--if-server-up")

const STUB = `// AUTO-GENERATED STUB — written by scripts/gen-api-types.mjs when the API was
// unreachable. Run \`npm run gen:api\` against a live API to replace this with
// real types.
export type paths = Record<string, never>
export type components = { schemas: Record<string, never> }
export type operations = Record<string, never>
`

function warn(msg) {
  process.stderr.write(`\x1b[33m[gen:api]\x1b[0m ${msg}\n`)
}

function info(msg) {
  process.stdout.write(`[gen:api] ${msg}\n`)
}

async function ensureStub() {
  mkdirSync(dirname(OUT_FILE), { recursive: true })
  if (!existsSync(OUT_FILE)) {
    writeFileSync(OUT_FILE, STUB, "utf8")
    info(`wrote stub -> ${OUT_FILE}`)
  } else {
    info(`kept existing ${OUT_FILE}`)
  }
}

async function main() {
  let openapiTypescript
  try {
    const mod = await import("openapi-typescript")
    openapiTypescript = mod.default ?? mod
  } catch (err) {
    if (SOFT) {
      warn(`openapi-typescript not installed; falling back to stub. (${err.message})`)
      await ensureStub()
      return
    }
    throw err
  }

  info(`fetching ${OPENAPI_URL}`)
  let output
  try {
    output = await openapiTypescript(new URL(OPENAPI_URL))
  } catch (err) {
    if (SOFT) {
      warn(`API unreachable at ${OPENAPI_URL} (${err.message}); skipping codegen.`)
      await ensureStub()
      return
    }
    throw err
  }

  mkdirSync(dirname(OUT_FILE), { recursive: true })
  writeFileSync(OUT_FILE, output, "utf8")
  info(`wrote ${OUT_FILE}`)
}

main().catch((err) => {
  process.stderr.write(`[gen:api] FAILED: ${err.stack ?? err.message}\n`)
  process.exit(1)
})
