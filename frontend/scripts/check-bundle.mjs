// Checks a production bundle. Run after building:
//   node scripts/check-bundle.mjs demo dist-demo   static demo: no backend address of any kind, no source maps, no
//                                                   third-party fonts, relative asset paths
//   node scripts/check-bundle.mjs app dist         normal build: carries its intended API address
// The address checked is VITE_API_URL if set, otherwise the default http://localhost:8000/api.
// Only backend addresses are checked: library strings such as React Router's internal "http://localhost" base and
// unrelated "/api" text are allowed.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const [mode, dir] = process.argv.slice(2)
const DEFAULT_API = 'http://localhost:8000/api'
const configured = (process.env.VITE_API_URL || '').replace(/\/$/, '')
const expected = configured || DEFAULT_API

if (!['demo', 'app'].includes(mode) || !dir) {
  console.error('Usage: node scripts/check-bundle.mjs demo|app <build folder>')
  process.exit(2)
}
if (!existsSync(join(dir, 'index.html'))) {
  console.error(`${dir}/index.html not found — build first.`)
  process.exit(2)
}

function files(folder) {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name)
    return statSync(path).isDirectory() ? files(path) : [path]
  })
}

const all = files(dir)
const text = all.filter((f) => /\.(html|js|css|json|txt|svg)$/.test(f)).map((f) => [f, readFileSync(f, 'utf8')])
const containing = (needle) => text.filter(([, content]) => content.includes(needle)).map(([f]) => f)
const problems = []

if (mode === 'demo') {
  for (const needle of new Set(['localhost:8000', DEFAULT_API, ...(configured ? [configured] : [])])) {
    const where = containing(needle)
    if (where.length) problems.push(`backend address "${needle}" found in ${where.join(', ')}`)
  }
  const maps = all.filter((f) => f.endsWith('.map'))
  if (maps.length) problems.push(`source maps found: ${maps.join(', ')}`)
  for (const host of ['fonts.googleapis.com', 'fonts.gstatic.com']) {
    if (containing(host).length) problems.push(`third-party font address "${host}" found`)
  }
  if (!readFileSync(join(dir, 'index.html'), 'utf8').includes('src="./assets/')) {
    problems.push('index.html does not load its script with a relative ./assets/ path')
  }
} else if (!containing(expected).length) {
  problems.push(`the normal build does not contain its API address "${expected}"`)
}

if (problems.length) {
  console.error(`check-bundle (${mode}) failed:\n  - ${problems.join('\n  - ')}`)
  process.exit(1)
}
console.log(`check-bundle (${mode}): OK — ${all.length} files checked in ${dir}`
  + (mode === 'demo' ? ', no backend address' : `, API address ${expected}`))
