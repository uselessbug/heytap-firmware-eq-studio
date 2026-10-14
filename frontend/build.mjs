import { build } from 'esbuild'
import { mkdir, copyFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.dirname(fileURLToPath(import.meta.url))
const output = path.resolve(root, '../src/heytap_eq/web')
await mkdir(output, { recursive: true })
await build({
  entryPoints: [path.join(root, 'src/editor.jsx')],
  outfile: path.join(output, 'editor.js'),
  bundle: true,
  minify: true,
  sourcemap: false,
  format: 'iife',
  target: 'chrome120',
  define: { 'process.env.NODE_ENV': '"production"' },
  loader: { '.woff': 'dataurl', '.woff2': 'dataurl', '.ttf': 'dataurl', '.svg': 'dataurl' },
  legalComments: 'linked'
})
await copyFile(path.join(root, 'index.html'), path.join(output, 'index.html'))
await copyFile(path.join(root, 'node_modules/dsssp/LICENSE'), path.join(output, 'DSSSP-LICENSE.txt'))
