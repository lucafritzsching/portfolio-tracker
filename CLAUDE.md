# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

No build step or package manager. Open `index.html` directly in a browser:

```
# On Windows
start index.html

# Or just double-click index.html in Explorer
```

Chart.js is loaded from CDN (`cdnjs.cloudflare.com`), so an internet connection is required for charts to render.

## Architecture

The entire application lives in a single file: `index.html`. It contains HTML, CSS (embedded `<style>`), and JavaScript (embedded `<script>`). There are no external files, no modules, and no build tooling.

**State:** Portfolio positions are stored in `localStorage` under the key `portfaio-portfolio` as a JSON array. The `save()` function persists after every mutation.

**Views:** Four views (`dashboard`, `stocks`, `news`, `analysis`) are toggled by showing/hiding `<div id="view-*">` elements. `showView(v)` handles the switching and triggers the appropriate render function.

**Data model** (each position object):
```js
{ ticker, name, shares, buyPrice, currentPrice, dayChange, sector, alerts: { news: true } }
```

**Signal logic** (`getSignal`): `>+20%` return → "Verkaufen", `<-12%` return → "Nachkaufen", `|dayChange| > 4%` → "Beobachten", else "Halten".

**Charts:** Two Chart.js doughnut charts (allocation and sector breakdown) rendered on the dashboard. References are kept in module-level `allocChart` / `sectorChart` variables and destroyed before re-render to avoid memory leaks.

**AI Analysis:** `analyzeStock(i)` and `runAIAnalysis()` call the Anthropic Messages API directly from the browser (`https://api.anthropic.com/v1/messages`, model `claude-sonnet-4-20250514`). The current code is missing the required `x-api-key` header — AI features will return 401 errors until a key is injected. Prompts are written in German and request responses in German.

**News:** The news feed in the News view is entirely mock/templated data generated from the portfolio array — there is no real news API integration.

**i18n:** The UI language is German throughout (labels, prompts, error messages).
