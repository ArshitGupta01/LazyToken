# npm package

LazyToken's npm command runs the local Python application. Node.js 18+ and Python 3.11+ must be installed. The package makes no model calls and does not download Python.

Create a publishable package from the current checkout in a new directory:

```powershell
node npm/stage.cjs C:\path\to\new-package-directory
npm pack C:\path\to\new-package-directory
```

After the package is published, `npx lazytoken serve` (or `npx lazytoken dashboard`) starts the local server and connects the browser, and `npx lazytoken --help` lists commands. The npm package must be published before those commands can fetch it.

For durable MCP setup, prefer installing a pinned package locally or globally: `npx` can remove its temporary package cache, which would invalidate a configured server path.
