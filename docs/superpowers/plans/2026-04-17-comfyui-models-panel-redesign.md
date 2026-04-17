# ComfyUI models panel — capability-first redesign: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "ComfyUI — diffusion models" panel in the dashboard with a capability-first view: a stacked disk-usage bar plus one expandable row per capability (video / image / encoder / upscale / style). Drop the raw file browser and the uninstalled-pack picker.

**Architecture:** A new `capability` string on each entry in `scripts/comfyui/models.json` drives the grouping. The backend passes it through in `/api/comfyui/packs`. A single frontend function `loadComfyuiPanel()` fetches both `/api/comfyui/packs` and `/api/comfyui/models`, filters to packs with `installed_count > 0`, groups them by capability, sums sizes from the file manifest, and renders header → disk bar → capability rows → (on expand) pack rows → (on expand) file rows. Two-level expand state is held in-page; the capability level persists to `localStorage`.

**Tech Stack:** FastAPI (dashboard backend), vanilla JS + CSS custom properties (dashboard frontend), pytest + `fastapi.testclient.TestClient` for the backend test.

**Repo layout reminder:** Windows host, bash shell, forward slashes in paths. Tests run with `pytest` from the repo root.

---

## Task 1: Add `capability` field to `scripts/comfyui/models.json`

Fixed, curated mapping from the design spec. No behavior change until later tasks consume it.

**Files:**
- Modify: `scripts/comfyui/models.json`

- [ ] **Step 1: Add `"capability"` key to each pack entry**

Every pack under `"packs"` gets a new `"capability"` field as its first key (just after the opening `{`). Use the keys below verbatim. If you see a pack name here not in the file, skip it; if you see a pack in the file not here, assign `"other"`.

```
ltx-2.3-fp8              → "video"
ltx-2.3-gguf             → "video"
ltx-2.3-extras           → "video"
ltx-2.3-t2v-basic        → "video"
sd15                     → "image"
sd35-medium              → "image"
sdxl                     → "image"
flux-schnell             → "image"
flux1-dev                → "image"
flux1-dev-gguf           → "image"
flux2-dev-gguf           → "image"
gemma-3-text-encoder-fp4 → "encoder"
gemma-3-text-encoder-gguf→ "encoder"
gemma-3-abliterated-lora → "encoder"
gemma-4-text-encoder     → "encoder"
flux2-text-encoder       → "encoder"
supir-upscaler           → "upscale"
scooby-doo-game-assets   → "style"
```

Concrete example for the first pack (all other packs follow the same shape — put `"capability"` before `"description"`):

```json
"ltx-2.3-fp8": {
  "capability": "video",
  "description": "LTX-2.3 22B dev — fp8 safetensors checkpoint (29 GB)",
  "models": [ ... ]
},
```

- [ ] **Step 2: Validate the JSON still parses**

Run from repo root:

```bash
python -c "import json; d=json.load(open('scripts/comfyui/models.json')); caps={p['capability'] for p in d['packs'].values()}; assert caps <= {'video','image','encoder','upscale','style','other'}, caps; print('ok', len(d['packs']), 'packs,', caps)"
```

Expected: `ok 18 packs, {...}` with capabilities from the allowed set.

- [ ] **Step 3: Commit**

```bash
git add scripts/comfyui/models.json
git commit -m "feat(comfyui): add capability field to model packs"
```

---

## Task 2: Write failing test — `/api/comfyui/packs` surfaces `capability` + per-pack files

TDD-first. Write the test before touching `dashboard/app.py`. Follows the existing dashboard test pattern (`tests/test_dashboard_health.py`).

Per the spec §Data flow step 2, the frontend looks up each installed pack's files "by matching filename + destination category (the pack's `models[].file` and `models[].dest`)." That requires the backend to expose each pack's resolved file list — not just counts. This task pins both additions (`capability` + `files`) in a single test.

**Files:**
- Create: `tests/test_dashboard_comfyui_packs.py`

- [ ] **Step 1: Write the failing test**

```python
"""Test that /api/comfyui/packs exposes capability + resolved per-pack files."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """Spin up the dashboard app without hitting real ComfyUI / services."""
    import dashboard.app as dashboard_app

    # /api/comfyui/packs calls _scan_comfyui_models via asyncio.to_thread; stub the
    # sync function so the test is hermetic even without a models/ directory.
    monkeypatch.setattr(dashboard_app, "_scan_comfyui_models", lambda: [])
    return TestClient(dashboard_app.app)


def test_packs_endpoint_exposes_capability_field(client):
    """Every pack in /api/comfyui/packs must include a 'capability' string."""
    r = client.get("/api/comfyui/packs")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True, data
    assert data["packs"], "expected at least one pack from models.json"
    allowed = {"video", "image", "encoder", "upscale", "style", "other"}
    for name, pack in data["packs"].items():
        assert "capability" in pack, f"pack {name!r} missing capability"
        assert pack["capability"] in allowed, (
            f"pack {name!r} has unknown capability {pack['capability']!r}"
        )


def test_packs_endpoint_exposes_resolved_files(client):
    """Every pack must include a 'files' list of {category, name} — resolved per {quant}."""
    r = client.get("/api/comfyui/packs")
    data = r.json()
    assert data["ok"] is True, data
    for name, pack in data["packs"].items():
        assert "files" in pack, f"pack {name!r} missing files"
        assert isinstance(pack["files"], list), f"pack {name!r} files not a list"
        assert len(pack["files"]) == pack["model_count"], (
            f"pack {name!r}: files length {len(pack['files'])} != model_count {pack['model_count']}"
        )
        for f in pack["files"]:
            assert set(f.keys()) >= {"category", "name"}, f
            assert "{quant}" not in f["name"], f"quant placeholder not resolved in {name!r}: {f}"
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
pytest tests/test_dashboard_comfyui_packs.py -v
```

Expected: both tests FAIL — the endpoint does not yet pass either field through.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_dashboard_comfyui_packs.py
git commit -m "test(dashboard): pin /api/comfyui/packs capability + files shape"
```

---

## Task 3: Backend — surface `capability` and per-pack `files` in `/api/comfyui/packs`

**Files:**
- Modify: `dashboard/app.py` around lines 843–855 (the dict comprehension that builds `packs[name]`).

- [ ] **Step 1: Resolve each pack's files and emit them alongside `capability`**

Find the block in `comfyui_packs()`:

```python
packs = {}
for name, pack in config.get("packs", {}).items():
    models = pack.get("models", [])
    installed_count = sum(
        1 for m in models
        if (m.get("dest", "checkpoints"), Path(m["file"].replace("{quant}", default_quant)).name) in installed
    )
    packs[name] = {
        "description": pack.get("description", ""),
        "model_count": len(models),
        "installed_count": installed_count,
    }
```

Replace with:

```python
packs = {}
for name, pack in config.get("packs", {}).items():
    models = pack.get("models", [])
    resolved_files = [
        {
            "category": m.get("dest", "checkpoints"),
            "name": Path(m["file"].replace("{quant}", default_quant)).name,
        }
        for m in models
    ]
    installed_count = sum(
        1 for f in resolved_files
        if (f["category"], f["name"]) in installed
    )
    packs[name] = {
        "capability": pack.get("capability", "other"),
        "description": pack.get("description", ""),
        "model_count": len(models),
        "installed_count": installed_count,
        "files": resolved_files,
    }
```

- [ ] **Step 2: Run the tests and verify they pass**

```bash
pytest tests/test_dashboard_comfyui_packs.py -v
```

Expected: both tests PASS.

- [ ] **Step 3: Sanity-check the wider dashboard test suite still passes**

```bash
pytest tests/test_dashboard_health.py tests/test_dashboard_comfyui_packs.py -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app.py
git commit -m "feat(dashboard): surface pack capability + resolved files in packs API"
```

---

## Task 4: Frontend — strip the old panel HTML

Remove the raw-file list, pack-picker checklist, download button, and pull-progress log. The "ComfyUI — diffusion models" panel becomes a single empty root element that later tasks will populate.

**Do NOT touch the `openclaw-sync-btn` block.** It lives in the separate **LLM — llama.cpp** panel (lines ~1400–1405) and is for syncing LLM models to OpenClaw, unrelated to ComfyUI. Leave it exactly where it is.

**Files:**
- Modify: `dashboard/static/index.html` lines ~1407–1425 (the `<div class="model-panel">` wrapping ComfyUI).

- [ ] **Step 1: Replace the panel markup**

Find the panel (the block whose `<h3>` reads `ComfyUI — diffusion models`):

```html
<div class="model-panel">
  <h3>ComfyUI — diffusion models</h3>
  <div class="model-list" id="comfyui-models">
    <div class="skeleton skeleton-line"></div>
    <div class="skeleton skeleton-line short"></div>
  </div>
  <div class="pull-area">
    <div id="comfyui-packs" style="margin-bottom:var(--space-3);">
      <div class="skeleton skeleton-line" style="width:70%"></div>
      <div class="skeleton skeleton-line" style="width:55%"></div>
    </div>
    <div class="pull-row">
      <button id="comfyui-pull">Download Selected Packs</button>
    </div>
    <div id="comfyui-progress" class="progress-area" style="display:none;" role="region" aria-label="ComfyUI pull progress">
      <div class="log" id="comfyui-log" role="log" aria-live="polite"></div>
    </div>
  </div>
</div>
```

Replace it with:

```html
<div class="model-panel">
  <h3>ComfyUI models</h3>
  <div id="comfyui-panel" class="comfy-panel" aria-busy="true">
    <div class="comfy-panel-summary" id="comfyui-panel-summary">
      <span class="skeleton skeleton-line" style="width:60%"></span>
    </div>
    <div class="comfy-disk-bar" id="comfyui-disk-bar" aria-label="Disk usage by capability"></div>
    <div class="comfy-disk-legend" id="comfyui-disk-legend"></div>
    <div class="comfy-cap-list" id="comfyui-cap-list">
      <div class="skeleton skeleton-line"></div>
      <div class="skeleton skeleton-line short"></div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Sanity-check the HTML**

Run:

```bash
grep -n 'id="comfyui-models"\|id="comfyui-packs"\|id="comfyui-pull"\|id="comfyui-progress"\|id="comfyui-log"' dashboard/static/index.html
```

Expected: no matches.

```bash
grep -n 'id="openclaw-sync-btn"' dashboard/static/index.html
```

Expected: exactly one match (unchanged — in the LLM panel).

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/index.html
git commit -m "refactor(dashboard): strip old ComfyUI file/pack-picker markup"
```

---

## Task 5: Add CSS for the disk bar and capability/pack/file rows

All new styles live in the same `<style>` block as `.comfy-cat-row` etc. (around lines ~685–715). Reuse the existing `--muted`, `--fg`, `--border`, `--surface-hover`, `--space-*` custom properties.

**Files:**
- Modify: `dashboard/static/index.html` — add a CSS block after the existing `.comfy-*` styles.

- [ ] **Step 1: Append the new CSS**

After the last existing `.comfy-file-item` rule, insert:

```css
/* --- Capability-first ComfyUI panel --- */
.comfy-panel { display: flex; flex-direction: column; gap: var(--space-3); }
.comfy-panel-summary {
  font-size: .82rem; color: var(--fg); font-family: var(--font-mono);
}
.comfy-panel-summary .muted { color: var(--muted); }

.comfy-disk-bar {
  display: flex; width: 100%; height: 10px; border-radius: 5px;
  overflow: hidden; background: var(--bg); border: 1px solid var(--border-subtle);
}
.comfy-disk-bar .seg { height: 100%; min-width: 2px; }
.comfy-disk-bar .seg.cap-video   { background: #7c5cff; }
.comfy-disk-bar .seg.cap-image   { background: #00c9ff; }
.comfy-disk-bar .seg.cap-encoder { background: #4cd97b; }
.comfy-disk-bar .seg.cap-upscale { background: #ffb547; }
.comfy-disk-bar .seg.cap-style   { background: #ff6ec7; }
.comfy-disk-bar .seg.cap-other   { background: var(--muted); }

.comfy-disk-legend {
  display: flex; flex-wrap: wrap; gap: var(--space-3);
  font-size: .7rem; color: var(--muted);
}
.comfy-disk-legend .swatch {
  display: inline-block; width: 8px; height: 8px; border-radius: 2px;
  margin-right: 4px; vertical-align: middle;
}

.comfy-cap-list { display: flex; flex-direction: column; }
.comfy-cap-row {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-3); cursor: pointer;
  border-top: 1px solid var(--border-subtle);
}
.comfy-cap-row:hover { background: var(--surface-hover); }
.comfy-cap-list .comfy-cap-row:first-child { border-top: none; }
.comfy-cap-chevron { font-size: .6rem; color: var(--muted); transition: transform .18s; flex-shrink: 0; }
.comfy-cap-row.open .comfy-cap-chevron { transform: rotate(90deg); }
.comfy-cap-label { flex: 1; min-width: 0; font-size: .82rem; color: var(--fg); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.comfy-cap-count, .comfy-cap-size { font-size: .72rem; color: var(--muted); white-space: nowrap; flex-shrink: 0; }

.comfy-pack-list { background: var(--bg); }
.comfy-pack-row {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-4); cursor: pointer;
  border-top: 1px solid var(--border-subtle); font-size: .78rem;
}
.comfy-pack-row:hover { background: var(--surface-hover); }
.comfy-pack-chevron { font-size: .55rem; color: var(--muted); transition: transform .18s; flex-shrink: 0; }
.comfy-pack-row.open .comfy-pack-chevron { transform: rotate(90deg); }
.comfy-pack-name { flex: 1; min-width: 0; color: var(--fg); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono); }
.comfy-pack-badge { font-size: .65rem; padding: 1px 6px; border-radius: 8px; flex-shrink: 0; }
.comfy-pack-badge.installed { color: var(--green, #4cd97b); border: 1px solid currentColor; }
.comfy-pack-badge.partial   { color: var(--muted); border: 1px solid currentColor; }
.comfy-pack-size { font-size: .7rem; color: var(--muted); white-space: nowrap; flex-shrink: 0; }

.comfy-pack-files { background: var(--bg); }
.comfy-pack-file {
  display: flex; align-items: center; gap: var(--space-2);
  padding: 4px var(--space-4) 4px calc(var(--space-4) + 12px);
  border-top: 1px solid var(--border-subtle); font-size: .72rem;
}
.comfy-pack-file .name { flex: 1; min-width: 0; color: var(--fg); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono); }
.comfy-pack-file .meta { color: var(--muted); white-space: nowrap; flex-shrink: 0; }
.comfy-pack-file .btn-model-delete {
  background: transparent; border: none; color: var(--muted); cursor: pointer;
  font-size: 1rem; line-height: 1; padding: 0 4px;
}
.comfy-pack-file .btn-model-delete:hover { color: var(--danger, #ff4d4f); }

.comfy-empty {
  padding: var(--space-4); text-align: center; font-size: .8rem; color: var(--muted);
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/static/index.html
git commit -m "style(dashboard): add CSS for capability-first ComfyUI panel"
```

---

## Task 6: Remove the old JS — `loadComfyuiModels`, `loadComfyuiPacks`, pull handler, state

Delete all code paths whose HTML anchors no longer exist (deleted in Task 4). Keep the file-delete endpoint wiring — Task 8 re-uses it under a new selector.

**Files:**
- Modify: `dashboard/static/index.html` (the single inline `<script>` block).

- [ ] **Step 1: Delete `async function loadComfyuiModels()`**

Delete the entire function body around lines ~2234–2287 (from `async function loadComfyuiModels() {` through its closing `}`).

- [ ] **Step 2: Delete `async function loadComfyuiPacks()`**

Delete the entire function body around lines ~2289–2321.

- [ ] **Step 3: Delete the `comfyui-pull` click handler**

Delete the block starting at `document.getElementById('comfyui-pull').onclick = async () => {` (around line 2488) through its closing `};` (around line 2529).

- [ ] **Step 4: Delete the `comfyui-models` click + keydown listeners**

Delete the two event listeners around lines 2802–2845 (`document.getElementById('comfyui-models')?.addEventListener('click', ...)` and the `keydown` sibling).

- [ ] **Step 5: Delete the leftover `comfyuiOpenCategories` state**

Delete the line around 1553: `const comfyuiOpenCategories = new Set();`.

- [ ] **Step 6: Update the call sites that referenced the deleted functions**

Find every remaining reference (there are three categories):

**a.** Initial page-load line (around 2662):

```js
await Promise.all([loadServices(), loadDependencies(), loadRagStatus(), loadOllamaModels(), loadComfyuiModels(), loadComfyuiPacks(), loadMcpServers()]);
```

Replace `loadComfyuiModels(), loadComfyuiPacks()` with `loadComfyuiPanel()`.

**b.** Hub Downloads success callback (around line 2612):

```js
if (s.success) { hubInput.value = ''; updateBadge(''); loadComfyuiModels?.(); }
```

Replace `loadComfyuiModels?.()` with `loadComfyuiPanel?.()`.

**c.** Any other calls (the pull-status poll, the delete handler — both deleted in prior steps, but if the grep finds survivors, convert them to `loadComfyuiPanel()` too).

Run:

```bash
grep -n 'loadComfyuiModels\|loadComfyuiPacks' dashboard/static/index.html
```

Expected: no matches after this step.

- [ ] **Step 7: Strip the ComfyUI branch of `resumeActivePulls()`**

Around line ~2910, `async function resumeActivePulls() { ... }` has a try-block that calls `/api/comfyui/pull/status` and, if running, grabs `comfyui-pull`, `comfyui-progress`, `comfyui-log` — all IDs deleted in Task 4. Remove the entire ComfyUI `try { ... } catch (_) {}` block (approximately lines 2911–2943). Keep the Ollama branch (and anything else in the function) unchanged. The `/api/comfyui/pull/status` endpoint still exists on the backend for CLI/script use; the dashboard no longer polls it because it no longer triggers pulls from the UI.

- [ ] **Step 8: Sanity-check that nothing still references deleted IDs**

```bash
grep -n 'comfyui-pull\|comfyui-log\|comfyui-progress\|comfyuiOpenCategories\|comfyui-packs' dashboard/static/index.html
```

Expected: no matches.

- [ ] **Step 9: Commit**

```bash
git add dashboard/static/index.html
git commit -m "refactor(dashboard): remove file-list + pack-picker JS"
```

---

## Task 7: Add `loadComfyuiPanel()` — fetch, group, render

This replaces all of the deleted JS with a single rendering entry point. Insert the new code where the old `loadComfyuiModels` used to live (around line 2234, immediately after the `throughput*` functions).

**Files:**
- Modify: `dashboard/static/index.html`.

- [ ] **Step 1: Add the capability metadata constant and helpers**

At the top of the inline `<script>` block near the other module-scope constants (e.g. near `const AUTH_STORAGE_KEY = ...` around line 1468, or adjacent to the `escapeHtml` helper at 1555), insert:

```js
const COMFY_CAPABILITIES = [
  { key: 'video',   label: 'Video generation' },
  { key: 'image',   label: 'Image generation' },
  { key: 'encoder', label: 'Text encoders' },
  { key: 'upscale', label: 'Upscaling' },
  { key: 'style',   label: 'Style LoRAs' },
  { key: 'other',   label: 'Other' },
];
const COMFY_CAP_OPEN_KEY = 'comfyui-open-caps';

function loadComfyOpenCaps() {
  try { return new Set(JSON.parse(localStorage.getItem(COMFY_CAP_OPEN_KEY) || '[]')); }
  catch (_) { return new Set(); }
}
function saveComfyOpenCaps(set) {
  try { localStorage.setItem(COMFY_CAP_OPEN_KEY, JSON.stringify([...set])); }
  catch (_) { /* ignore quota/privacy errors */ }
}
```

- [ ] **Step 2: Add `loadComfyuiPanel()` and its render helpers**

Insert this block at the location where `loadComfyuiModels` was (around line 2234, after `loadPerfKPIs()` / before the `loadOllamaModels` section — match the surrounding indentation of 4 spaces):

```js
    async function loadComfyuiPanel() {
      const root = document.getElementById('comfyui-panel');
      const capList = document.getElementById('comfyui-cap-list');
      const summary = document.getElementById('comfyui-panel-summary');
      const bar = document.getElementById('comfyui-disk-bar');
      const legend = document.getElementById('comfyui-disk-legend');
      if (!root) return;
      root.setAttribute('aria-busy', 'true');
      try {
        const [packsResp, modelsResp] = await Promise.all([
          api('/api/comfyui/packs').then(r => r.json()),
          api('/api/comfyui/models').then(r => r.json()),
        ]);
        if (!packsResp.ok || !modelsResp.ok) {
          capList.innerHTML = '<div class="comfy-empty">Failed to load models.</div>';
          summary.textContent = '';
          bar.innerHTML = '';
          legend.innerHTML = '';
          return;
        }
        // Index files on disk by "category/name" so we can look up bytes per pack file.
        const diskIndex = new Map();
        for (const m of modelsResp.models || []) {
          const bytes = Number(m.size_bytes ?? (m.size_mb ?? 0) * 1e6);
          diskIndex.set(`${m.category}/${m.name}`, bytes);
        }
        // Enrich each installed pack with on-disk file entries + total bytes.
        const installedPacks = [];
        for (const [name, pack] of Object.entries(packsResp.packs || {})) {
          if (!pack.installed_count || pack.installed_count <= 0) continue;
          const files = (pack.files || []).map(f => {
            const key = `${f.category}/${f.name}`;
            return {
              category: f.category,
              name: f.name,
              bytes: diskIndex.get(key) ?? 0,
              onDisk: diskIndex.has(key),
            };
          });
          const bytes = files.reduce((s, f) => s + f.bytes, 0);
          installedPacks.push({
            name,
            capability: pack.capability || 'other',
            description: pack.description || '',
            installed: pack.installed_count,
            total: pack.model_count,
            files,
            bytes,
          });
        }
        // Per-capability totals (sum of bytes across that capability's installed packs).
        const capTotals = new Map();
        const capsByInstalled = new Map();
        for (const p of installedPacks) {
          capTotals.set(p.capability, (capTotals.get(p.capability) || 0) + p.bytes);
          if (!capsByInstalled.has(p.capability)) capsByInstalled.set(p.capability, []);
          capsByInstalled.get(p.capability).push(p);
        }
        const grandBytes = [...capTotals.values()].reduce((a, b) => a + b, 0);
        // Header summary.
        summary.innerHTML = `<strong>${formatSize(grandBytes)}</strong> <span class="muted">on disk · ${installedPacks.length} pack${installedPacks.length === 1 ? '' : 's'} installed</span>`;
        // Disk bar. One segment per capability with >0 bytes, ordered by COMFY_CAPABILITIES.
        const orderedCaps = COMFY_CAPABILITIES.filter(c => (capTotals.get(c.key) || 0) > 0);
        bar.innerHTML = orderedCaps.map(c => {
          const bytes = capTotals.get(c.key) || 0;
          const pct = grandBytes ? (bytes / grandBytes * 100) : 0;
          return `<span class="seg cap-${c.key}" style="width:${pct.toFixed(2)}%;" title="${escapeHtml(c.label)} — ${formatSize(bytes)}"></span>`;
        }).join('');
        legend.innerHTML = orderedCaps.map(c => {
          const bytes = capTotals.get(c.key) || 0;
          return `<span><span class="swatch cap-${c.key}"></span>${escapeHtml(c.label)} ${formatSize(bytes)}</span>`;
        }).join('');
        // Capability rows.
        const openCaps = loadComfyOpenCaps();
        const rowCaps = COMFY_CAPABILITIES.filter(c => capsByInstalled.has(c.key));
        if (!rowCaps.length) {
          capList.innerHTML = '<div class="comfy-empty">No models installed. Pull models from Hub Downloads above.</div>';
          return;
        }
        capList.innerHTML = rowCaps.map(c => {
          const packs = capsByInstalled.get(c.key);
          const isOpen = openCaps.has(c.key);
          const capBytes = capTotals.get(c.key) || 0;
          return `
            <div class="comfy-cap-group" data-cap="${escapeHtml(c.key)}">
              <div class="comfy-cap-row${isOpen ? ' open' : ''}" data-cap="${escapeHtml(c.key)}" role="button" tabindex="0" aria-expanded="${isOpen ? 'true' : 'false'}">
                <span class="comfy-cap-chevron">&#9656;</span>
                <span class="comfy-cap-label">${escapeHtml(c.label)}</span>
                <span class="comfy-cap-count">${packs.length} pack${packs.length === 1 ? '' : 's'}</span>
                <span class="comfy-cap-size">${formatSize(capBytes)}</span>
              </div>
              <div class="comfy-pack-list" style="${isOpen ? '' : 'display:none;'}">
                ${packs.map(p => renderPackRow(p)).join('')}
              </div>
            </div>
          `;
        }).join('');
      } catch (e) {
        capList.innerHTML = '<div class="comfy-empty">Failed to load models.</div>';
      } finally {
        root.setAttribute('aria-busy', 'false');
      }
    }

    function renderPackRow(pack) {
      const partial = pack.installed < pack.total;
      const badge = partial
        ? `<span class="comfy-pack-badge partial">${pack.installed}/${pack.total}</span>`
        : `<span class="comfy-pack-badge installed">✓ ${pack.installed}</span>`;
      const onDisk = pack.files.filter(f => f.onDisk);
      const filesHtml = onDisk.map(f => `
        <div class="comfy-pack-file">
          <span class="name" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>
          <span class="meta">${formatSize(f.bytes)}</span>
          <button type="button" class="btn-model-delete" data-category="${escapeHtml(f.category)}" data-filename="${escapeHtml(f.name)}" title="Delete" aria-label="Delete ${escapeHtml(f.name)}">&times;</button>
        </div>
      `).join('');
      return `
        <div class="comfy-pack-group" data-pack="${escapeHtml(pack.name)}">
          <div class="comfy-pack-row" data-pack="${escapeHtml(pack.name)}" role="button" tabindex="0" aria-expanded="false">
            <span class="comfy-pack-chevron">&#9656;</span>
            <span class="comfy-pack-name" title="${escapeHtml(pack.description)}">${escapeHtml(pack.name)}</span>
            ${badge}
            <span class="comfy-pack-size">${formatSize(pack.bytes)}</span>
          </div>
          <div class="comfy-pack-files" style="display:none;">${filesHtml || '<div class="comfy-pack-file"><span class="name muted">No files on disk.</span></div>'}</div>
        </div>
      `;
    }
```

Note: `formatSize` already exists in the file (it's the same helper the old code used). Reuse it as-is.

- [ ] **Step 3: Wire interactions (capability expand/collapse, pack expand, file delete)**

Add a single event delegate at the end of the script block (immediately before the hardware-stats section around line ~2847). Be aware there is a generic delete handler higher up that listened on the now-removed `comfyui-models` element — that was already deleted in Task 6; this new delegate replaces it.

```js
    document.getElementById('comfyui-panel')?.addEventListener('click', async (e) => {
      const capRow = e.target.closest('.comfy-cap-row[data-cap]');
      if (capRow && !e.target.closest('.btn-model-delete')) {
        const cap = capRow.dataset.cap;
        const body = capRow.nextElementSibling;
        if (!body) return;
        const willOpen = body.style.display === 'none';
        body.style.display = willOpen ? '' : 'none';
        capRow.classList.toggle('open', willOpen);
        capRow.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        const open = loadComfyOpenCaps();
        if (willOpen) open.add(cap); else open.delete(cap);
        saveComfyOpenCaps(open);
        return;
      }
      const packRow = e.target.closest('.comfy-pack-row[data-pack]');
      if (packRow && !e.target.closest('.btn-model-delete')) {
        const body = packRow.nextElementSibling;
        if (!body) return;
        const willOpen = body.style.display === 'none';
        body.style.display = willOpen ? '' : 'none';
        packRow.classList.toggle('open', willOpen);
        packRow.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        return;
      }
      const delBtn = e.target.closest('.btn-model-delete[data-category]');
      if (!delBtn) return;
      e.preventDefault();
      const cat = delBtn.dataset.category;
      const filename = delBtn.dataset.filename;
      if (!cat || !filename) return;
      if (!confirm(`Delete ComfyUI model "${filename}" from ${cat}? This cannot be undone.`)) return;
      delBtn.disabled = true;
      try {
        const r = await api('/api/comfyui/models/' + encodeURIComponent(cat) + '/' + encodeURIComponent(filename), { method: 'DELETE' });
        const d = await r.json();
        if (r.ok) {
          toast(d.message || 'Model deleted');
          loadComfyuiPanel();
        } else {
          toast((d.detail || 'Delete failed') + '', 'error');
        }
      } catch (err) {
        toast('Delete failed: ' + (err.message || err), 'error');
      } finally {
        delBtn.disabled = false;
      }
    });

    document.getElementById('comfyui-panel')?.addEventListener('keydown', (e) => {
      if ((e.key !== 'Enter' && e.key !== ' ')) return;
      if (!e.target.matches('.comfy-cap-row[data-cap], .comfy-pack-row[data-pack]')) return;
      e.preventDefault();
      e.target.click();
    });
```

- [ ] **Step 4: Smoke-check the HTML parses**

Launch the dashboard locally (user's environment). Or at minimum verify no duplicate IDs / syntax errors:

```bash
python -c "import html.parser as h; p=h.HTMLParser(); p.feed(open('dashboard/static/index.html', encoding='utf-8').read()); print('parsed ok')"
```

Expected: `parsed ok`.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): render ComfyUI models as capability-first panel"
```

---

## Task 8: Manual verification

The panel is a pure UI change; automated coverage stops at Task 3. Walk through the checklist in a running dashboard.

**Files:** none (verification only).

- [ ] **Step 1: Start the dashboard**

```bash
docker compose up -d dashboard
```

Or if running natively:

```bash
uvicorn dashboard.app:app --reload
```

Open the dashboard URL in a browser. Log in if auth is enabled.

- [ ] **Step 2: Verify the empty state**

On a host with no models installed: the panel shows `"No models installed. Pull models from Hub Downloads above."` and the disk bar is empty. No skeletons are stuck.

- [ ] **Step 3: Verify the populated state**

On a host with models installed:
- Header shows total disk (e.g. `65.4 GB on disk · 8 packs installed`).
- Disk bar renders with colored segments; hover each segment shows the capability label + size in a native tooltip.
- Legend lists each capability with a swatch and size.
- Capability rows appear in the order listed in `COMFY_CAPABILITIES`, only rows with ≥1 installed pack are shown.
- Clicking a capability row expands it and shows the installed packs inside, each with status badge + size.
- Clicking a pack row expands it and shows each file's name + size + × delete button.
- Capability expand state survives a browser refresh (persisted via `localStorage`); pack expand state does not.

- [ ] **Step 4: Verify the delete flow**

Expand any pack and click the × on a small file. Confirm the native prompt. After confirming, the file disappears from the pack, the pack's byte count drops, the capability's byte count drops, and the disk bar re-proportions. If the file was the last one in a pack, the pack row disappears; if it was the last pack in a capability, the capability row disappears.

- [ ] **Step 5: Confirm Hub Downloads still triggers a panel reload**

From the Hub Downloads section above, pull any small diffusion model that is part of a known pack (e.g. the SD 1.5 pruned checkpoint for the `sd15` pack). After success, the ComfyUI panel re-fetches and the pack appears under its capability. A file pulled that does NOT belong to any pack will NOT appear in the panel — this is expected (the panel is pack-centric by design).

- [ ] **Step 6: Confirm no regressions elsewhere on the dashboard**

- `openclaw-sync-btn` still present and working inside the LLM / llama.cpp panel.
- No JS errors in the browser console across the full dashboard page.

- [ ] **Step 7: Final commit if any fixes were required during verification**

If Step 2–6 uncovered bugs, fix them inline and commit with a descriptive message (`fix(dashboard): <what>`). Otherwise nothing to do here.

---

## Self-review checklist (read before handoff)

- [x] Spec §Motivation → file-list + pack-picker stripped in Tasks 4 + 6.
- [x] Spec §Goals capability-first view → Tasks 1, 3, 7 (manifest capability field + backend pass-through + renderer).
- [x] Spec §Goals disk bar → Task 7 renders `#comfyui-disk-bar`, styled in Task 5.
- [x] Spec §Goals raw files only on drill-in → Task 7 `renderPackRow` shows files only when expanded; Task 8 verifies.
- [x] Spec §Goals uninstalled packs hidden → Task 7 filters `installed_count > 0`.
- [x] Spec §Non-goals no pull pipeline changes → endpoints `/api/comfyui/pull*` untouched; only the UI pack-picker is deleted.
- [x] Spec §Capability groups mapping → Task 1 spells out every pack; `capability` field rides through Tasks 2–3.
- [x] Spec §Layout (header + bar + rows + empty-state) → Tasks 4, 5, 7.
- [x] Spec §Data flow pack ∩ model join → Task 3 exposes `pack.files`, Task 7 joins to disk bytes directly (no heuristics).
- [x] Spec §Interactions localStorage persistence → Task 7 `loadComfyOpenCaps` / `saveComfyOpenCaps`.
- [x] Spec §Code touch points — all three files covered across Tasks 1–7. Note: the spec mentioned moving the Sync to OpenClaw button into the new header; this plan deliberately does not do so, because that button lives in the LLM / llama.cpp panel and is unrelated to ComfyUI. The spec is correspondingly slightly inaccurate on this point, but the plan chooses the correct behavior.

**Known residuals:** None. The backend addition of `pack.files` in Task 3 removes the earlier drafted v1 approximation; per-pack drill-down shows exact file names and sizes.
