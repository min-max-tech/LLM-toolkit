# MCP Context Management — Robust Tool-Call System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the openclaw-mcp-bridge against local GGUF model failures by adding object-field coercion, tiered retry budgets with feedback injection, response truncation, model-tier detection, and bootstrap compression.

**Architecture:** All runtime changes live in `dist/index.js` (the compiled bridge plugin). Config schema changes touch `dist/config-schema.js` and `openclaw.plugin.json`. Bootstrap compression is TOOLS.md edits + env var tuning. No new services.

**Tech Stack:** Vanilla ES module JavaScript (Node ≥22), Python pytest for contract tests (static string assertions on the compiled JS), TypeBox for schema definitions.

---

## File Map

| File | Role |
|------|------|
| `openclaw/extensions/openclaw-mcp-bridge/dist/index.js` | All runtime logic: coercion, retry, truncation, model-tier detection |
| `openclaw/extensions/openclaw-mcp-bridge/dist/config-schema.js` | Add `ggufMode` config option |
| `openclaw/extensions/openclaw-mcp-bridge/openclaw.plugin.json` | Add `ggufMode` to inline JSON schema |
| `tests/test_openclaw_mcp_bridge_contract.py` | Contract tests (static assertions on dist/index.js) |
| `openclaw/workspace/TOOLS.md` | Compress to ≤1400 chars |
| `openclaw/workspace/HEARTBEAT.md.example` | Replace with 3-line stub |
| `.env` | Add `OPENCLAW_BOOTSTRAP_TOTAL_MAX_CHARS=12000` |

---

## Task 1: Layer 1a — Loosen object-type fields in schema builder

**Context:** `buildLooseToolSchema()` already adds string fallbacks for `integer`/`number`/`boolean`. It does NOT do this for `object` types. When Gemma sends `overrides: "{height:1024"`, OpenClaw's schema validation rejects it before the bridge's `execute()` is called. Fix: add a string-fallback variant for anyOf schemas that contain an object type, and for direct `{ type: "object" }` schemas.

**Files:**
- Test: `tests/test_openclaw_mcp_bridge_contract.py`
- Modify: `openclaw/extensions/openclaw-mcp-bridge/dist/index.js` (function `buildLooseToolSchema`, lines ~76–130)

- [ ] **Step 1: Write the failing contract test**

Add to `tests/test_openclaw_mcp_bridge_contract.py`:

```python
def test_mcp_bridge_loosens_object_type_schema():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    # String fallback added when anyOf contains an object variant
    assert "hasObjectType" in text
    assert "object-string fallback" in text
    # Direct object type also gets a string fallback
    assert "anyOf: [loosened, stringFallback]" in text
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\dev\AI-toolkit
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_loosens_object_type_schema -v
```

Expected: FAIL — strings not yet in index.js.

- [ ] **Step 3: Implement — modify buildLooseToolSchema in dist/index.js**

Find the anyOf branch (around line 81):

```javascript
    if (Array.isArray(schema.anyOf)) {
        return {
            ...schema,
            anyOf: schema.anyOf.map((entry) => buildLooseToolSchema(entry)),
        };
    }
```

Replace with:

```javascript
    if (Array.isArray(schema.anyOf)) {
        const mapped = schema.anyOf.map((entry) => buildLooseToolSchema(entry));
        // object-string fallback: if anyOf contains an object variant, also accept a string
        // so models that emit JSON object strings (e.g. overrides: "{...}") pass validation.
        const hasObjectType = mapped.some((v) => v && typeof v === "object" && !Array.isArray(v) && v.type === "object");
        const hasStringFallback = mapped.some((v) => v && typeof v === "object" && !Array.isArray(v) && v.type === "string");
        if (hasObjectType && !hasStringFallback) {
            mapped.push({
                type: "string",
                description: "object-string fallback: pass a JSON object string; the bridge will parse and repair it before forwarding.",
            });
        }
        return { ...schema, anyOf: mapped };
    }
```

Find the direct object type branch (around line 99):

```javascript
    if (schema.type === "object") {
        const properties = schema.properties && typeof schema.properties === "object"
            ? Object.fromEntries(Object.entries(schema.properties).map(([key, value]) => [key, buildLooseToolSchema(value)]))
            : schema.properties;
        const additionalProperties = schema.additionalProperties && typeof schema.additionalProperties === "object"
            ? buildLooseToolSchema(schema.additionalProperties)
            : schema.additionalProperties;
        return {
            ...schema,
            properties,
            additionalProperties,
        };
    }
```

Replace with:

```javascript
    if (schema.type === "object") {
        const properties = schema.properties && typeof schema.properties === "object"
            ? Object.fromEntries(Object.entries(schema.properties).map(([key, value]) => [key, buildLooseToolSchema(value)]))
            : schema.properties;
        const additionalProperties = schema.additionalProperties && typeof schema.additionalProperties === "object"
            ? buildLooseToolSchema(schema.additionalProperties)
            : schema.additionalProperties;
        const loosened = { ...schema, properties, additionalProperties };
        const stringFallback = {
            type: "string",
            description: "object-string fallback: pass a JSON object string; the bridge will parse and repair it before forwarding.",
        };
        return { anyOf: [loosened, stringFallback] };
    }
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_loosens_object_type_schema -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```
pytest tests/test_openclaw_mcp_bridge_contract.py -v
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```
git add tests/test_openclaw_mcp_bridge_contract.py openclaw/extensions/openclaw-mcp-bridge/dist/index.js
git commit -m "feat(bridge): loosen schema to accept string fallback for object-typed fields"
```

---

## Task 2: Layer 1b — coerceObjectField() + coerceFlatToolValue object branch

**Context:** Schema validation now allows a string value for object fields. The bridge's `coerceFlatToolValue()` needs to repair that string into an actual object before forwarding to the MCP gateway. Add `coerceObjectField()` that reuses the existing `coerceToolArgs()` JSON-repair pipeline.

**Files:**
- Test: `tests/test_openclaw_mcp_bridge_contract.py`
- Modify: `openclaw/extensions/openclaw-mcp-bridge/dist/index.js` (after `coerceToolArgs`, inside `coerceFlatToolValue`)

- [ ] **Step 1: Write the failing contract test**

Add to `tests/test_openclaw_mcp_bridge_contract.py`:

```python
def test_mcp_bridge_coerces_object_string_fields():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    assert "function coerceObjectField(value)" in text
    assert "return coerceToolArgs(value)" in text
    # coerceFlatToolValue calls it for string values in object context
    assert "return coerceObjectField(value)" in text
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_coerces_object_string_fields -v
```

Expected: FAIL.

- [ ] **Step 3: Add coerceObjectField() to dist/index.js**

Insert this function immediately after the closing brace of `coerceToolArgs()` (around line 353):

```javascript
function coerceObjectField(value) {
    if (typeof value !== "string") {
        return value;
    }
    try {
        return coerceToolArgs(value);
    }
    catch {
        return value;
    }
}
```

- [ ] **Step 4: Modify coerceFlatToolValue() object branch**

Find the object branch in `coerceFlatToolValue()` (around line 419):

```javascript
    if (schema.type === "object") {
        if (!value || typeof value !== "object" || Array.isArray(value)) {
            return value;
        }
```

Replace the early-return line with:

```javascript
    if (schema.type === "object") {
        if (!value || typeof value !== "object" || Array.isArray(value)) {
            if (typeof value === "string") {
                return coerceObjectField(value);
            }
            return value;
        }
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_coerces_object_string_fields -v
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```
pytest tests/test_openclaw_mcp_bridge_contract.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add tests/test_openclaw_mcp_bridge_contract.py openclaw/extensions/openclaw-mcp-bridge/dist/index.js
git commit -m "feat(bridge): add coerceObjectField to repair JSON-string object args before forwarding"
```

---

## Task 3: Layer 1c — Integer trailing artifact fix

**Context:** Gemma emits integers as `"576]"`, `"1024)"` due to tokenizer artifacts. The existing int coercion strips commas but not trailing brackets and quotes. One regex addition fixes it.

**Files:**
- Test: `tests/test_openclaw_mcp_bridge_contract.py`
- Modify: `openclaw/extensions/openclaw-mcp-bridge/dist/index.js` (`coerceFlatToolValue` integer branch, ~line 389)

- [ ] **Step 1: Write the failing contract test**

Add to `tests/test_openclaw_mcp_bridge_contract.py`:

```python
def test_mcp_bridge_strips_integer_trailing_artifacts():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    # Regex that strips trailing ], ), ", ' from integer strings
    assert r'.replace(/[\])"\']+$/, "")' in text
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_strips_integer_trailing_artifacts -v
```

Expected: FAIL.

- [ ] **Step 3: Modify the integer coercion path in coerceFlatToolValue()**

Find (around line 389):

```javascript
    if (schema.type === "integer" || schema.type === "number") {
        if (typeof value === "string") {
            const cleaned = sanitizeModelToolText(value).replace(/,/g, "").trim();
```

Replace with:

```javascript
    if (schema.type === "integer" || schema.type === "number") {
        if (typeof value === "string") {
            const cleaned = sanitizeModelToolText(value).replace(/,/g, "").replace(/[\])"']+$/, "").trim();
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_strips_integer_trailing_artifacts -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/test_openclaw_mcp_bridge_contract.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```
git add tests/test_openclaw_mcp_bridge_contract.py openclaw/extensions/openclaw-mcp-bridge/dist/index.js
git commit -m "feat(bridge): strip trailing ] ) quote artifacts from integer/number strings"
```

---

## Task 4: Layer 5 — ggufMode config option + IS_LOCAL_GGUF detection

**Context:** The bridge needs to know whether it's running with a local GGUF model so it can apply lower retry thresholds and tighter response caps. Add a `ggufMode` boolean to the plugin config (so users can explicitly set it) with env-var detection as a fallback.

**Files:**
- Test: `tests/test_openclaw_mcp_bridge_contract.py`
- Modify: `openclaw/extensions/openclaw-mcp-bridge/dist/index.js` (start of `register()`)
- Modify: `openclaw/extensions/openclaw-mcp-bridge/dist/config-schema.js` (add `ggufMode`)
- Modify: `openclaw/extensions/openclaw-mcp-bridge/openclaw.plugin.json` (add `ggufMode` to inline schema)

- [ ] **Step 1: Write the failing contract test**

Add to `tests/test_openclaw_mcp_bridge_contract.py`:

```python
def test_mcp_bridge_model_tier_detection():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    assert "let IS_LOCAL_GGUF = false;" in text
    assert "IS_LOCAL_GGUF = true;" in text
    # Detection checks
    assert r"/\.gguf/i" in text
    assert r"/q[45678]_/i" in text
    assert 'api.logger.info("[mcp-bridge] GGUF mode' in text
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_model_tier_detection -v
```

Expected: FAIL.

- [ ] **Step 3: Add ggufMode to dist/config-schema.js**

Find the closing of the `configSchema` Type.Object (around line 88):

```javascript
    flatTools: Type.Optional(Type.Boolean({
        default: false,
        description: "Register individual flat tools per MCP tool (eager discovery). When false, only gateway__call is available.",
    })),
});
```

Replace with:

```javascript
    flatTools: Type.Optional(Type.Boolean({
        default: false,
        description: "Register individual flat tools per MCP tool (eager discovery). When false, only gateway__call is available.",
    })),
    ggufMode: Type.Optional(Type.Boolean({
        default: false,
        description: "Enable GGUF-mode: lower retry thresholds and tighter response caps for local quantized models. Auto-detected from OPENCLAW_MODEL env var if not set.",
    })),
});
```

- [ ] **Step 4: Add ggufMode to openclaw.plugin.json**

Find the `flatTools` entry near the end:

```json
      "flatTools": {
        "type": "boolean",
        "description": "Register individual flat tools per MCP tool (eager discovery). When false, only gateway__call is available.",
        "default": false
      }
    }
```

Replace with:

```json
      "flatTools": {
        "type": "boolean",
        "description": "Register individual flat tools per MCP tool (eager discovery). When false, only gateway__call is available.",
        "default": false
      },
      "ggufMode": {
        "type": "boolean",
        "description": "Enable GGUF-mode: lower retry thresholds and tighter response caps for local quantized models. Auto-detected from OPENCLAW_MODEL env var if not set.",
        "default": false
      }
    }
```

- [ ] **Step 5: Add IS_LOCAL_GGUF module variable and detection to dist/index.js**

Add this line immediately before the `function register(api)` declaration (around line 850):

```javascript
let IS_LOCAL_GGUF = false;
```

At the very start of `register(api)`, after `const config = api.pluginConfig;`, add:

```javascript
    // Model-tier detection: explicit config overrides env-var auto-detection.
    if (config?.ggufMode === true) {
        IS_LOCAL_GGUF = true;
    } else if (config?.ggufMode !== false) {
        // Auto-detect from active model string
        const activeModel = (
            process.env.OPENCLAW_MODEL ??
            process.env.OPENCLAW_DEFAULT_MODEL ??
            ""
        ).toLowerCase();
        if (/\.gguf/i.test(activeModel) || /q[45678]_/i.test(activeModel) || activeModel.includes("gguf")) {
            IS_LOCAL_GGUF = true;
        }
    }
    if (IS_LOCAL_GGUF) {
        api.logger.info("[mcp-bridge] GGUF mode active — lower retry thresholds and tighter response caps enabled");
    }
```

- [ ] **Step 6: Run test to verify it passes**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_model_tier_detection -v
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

```
pytest tests/test_openclaw_mcp_bridge_contract.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```
git add tests/test_openclaw_mcp_bridge_contract.py \
    openclaw/extensions/openclaw-mcp-bridge/dist/index.js \
    openclaw/extensions/openclaw-mcp-bridge/dist/config-schema.js \
    openclaw/extensions/openclaw-mcp-bridge/openclaw.plugin.json
git commit -m "feat(bridge): add ggufMode config + IS_LOCAL_GGUF detection for tier-aware coercion"
```

---

## Task 5: Layer 2 — Retry state utilities

**Context:** Add file-backed retry state functions. State lives in `SESSION_STATUS_DIR/retry/`. Each state file is keyed by session key + tool slug and has a 30-minute TTL. These are pure utilities — not wired into the handler yet.

**Files:**
- Test: `tests/test_openclaw_mcp_bridge_contract.py`
- Modify: `openclaw/extensions/openclaw-mcp-bridge/dist/index.js` (after `writeSessionStatus`, ~line 616)

- [ ] **Step 1: Write the failing contract test**

Add to `tests/test_openclaw_mcp_bridge_contract.py`:

```python
def test_mcp_bridge_retry_state_utilities():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    assert "const RETRY_TTL_MS = 30 * 60 * 1000;" in text
    assert "function retryStatePath(sessionKey, toolSlug)" in text
    assert "function readRetryState(sessionKey, toolSlug)" in text
    assert "function writeRetryState(sessionKey, toolSlug, patch)" in text
    assert "function clearRetryState(sessionKey, toolSlug)" in text
    assert "RETRY_TTL_MS" in text
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_retry_state_utilities -v
```

Expected: FAIL.

- [ ] **Step 3: Add retry state utilities to dist/index.js**

Insert immediately after the closing brace of `writeSessionStatus()` (after line 616):

```javascript
// ---------------------------------------------------------------------------
// Retry state — per-session-per-tool failure tracking
// ---------------------------------------------------------------------------
const RETRY_TTL_MS = 30 * 60 * 1000; // 30 minutes
const RETRY_DIR = path.join(SESSION_STATUS_DIR, "retry");

function retryStatePath(sessionKey, toolSlug) {
    const safeKey = (sessionKey || "default").replace(/[^A-Za-z0-9._-]+/g, "_");
    const safeSlug = toolSlug.replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60);
    return path.join(RETRY_DIR, `${safeKey}__${safeSlug}.json`);
}

async function readRetryState(sessionKey, toolSlug) {
    try {
        const raw = await fs.readFile(retryStatePath(sessionKey, toolSlug), "utf8");
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") {
            return null;
        }
        if (Date.now() - (parsed.ts ?? 0) > RETRY_TTL_MS) {
            await clearRetryState(sessionKey, toolSlug);
            return null;
        }
        return parsed;
    }
    catch {
        return null;
    }
}

async function writeRetryState(sessionKey, toolSlug, patch) {
    try {
        await fs.mkdir(RETRY_DIR, { recursive: true });
        const current = await readRetryState(sessionKey, toolSlug) ?? {};
        const next = { ...current, ...patch, ts: Date.now() };
        await fs.writeFile(retryStatePath(sessionKey, toolSlug), JSON.stringify(next), "utf8");
    }
    catch {
        // Best-effort: write failure means this attempt is not counted toward the retry budget.
    }
}

async function clearRetryState(sessionKey, toolSlug) {
    try {
        await fs.unlink(retryStatePath(sessionKey, toolSlug));
    }
    catch {
        // File may not exist — ignore.
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_retry_state_utilities -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/test_openclaw_mcp_bridge_contract.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```
git add tests/test_openclaw_mcp_bridge_contract.py openclaw/extensions/openclaw-mcp-bridge/dist/index.js
git commit -m "feat(bridge): add file-backed retry state utilities with 30-min TTL"
```

---

## Task 6: Layer 2 — Retry tier logic + feedback injection wired into flat tool handler

**Context:** Add three functions — `getRetryThresholds()`, `buildFeedbackMessage()`, `buildCapMessage()` — then rewrite the flat tool `execute()` handler to use them. Also add `let currentSessionKey = ""` inside `register()` and update it in the `message_received` hook so the execute handler can track retry state per session.

**Files:**
- Test: `tests/test_openclaw_mcp_bridge_contract.py`
- Modify: `openclaw/extensions/openclaw-mcp-bridge/dist/index.js`

- [ ] **Step 1: Write the failing contract test**

Add to `tests/test_openclaw_mcp_bridge_contract.py`:

```python
def test_mcp_bridge_retry_tier_logic():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    assert "function getRetryThresholds()" in text
    assert "function buildFeedbackMessage(" in text
    assert "function buildCapMessage(" in text
    assert "Do not retry this tool call." in text
    assert "Stop retrying with the same arguments." in text
    assert "let currentSessionKey" in text
    assert "currentSessionKey = key;" in text
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_retry_tier_logic -v
```

Expected: FAIL.

- [ ] **Step 3: Add tier helper functions to dist/index.js**

Insert these three functions immediately after `clearRetryState()` (end of the retry state block added in Task 5):

```javascript
function getRetryThresholds() {
    // GGUF models correct themselves poorly from feedback — escalate sooner.
    return IS_LOCAL_GGUF
        ? { feedbackAt: 2, capAt: 4 }
        : { feedbackAt: 3, capAt: 5 };
}

function buildFeedbackMessage(toolName, attempts, capAt, lastError, schema) {
    const lines = [
        `Tool call rejected (attempt ${String(attempts)} of ${String(capAt)}) — ${toolName}`,
        "",
        "Error returned:",
        `  ${lastError}`,
        "",
    ];
    const props = schema?.properties && typeof schema.properties === "object" ? schema.properties : {};
    const required = Array.isArray(schema?.required) ? schema.required : [];
    if (Object.keys(props).length > 0) {
        lines.push("Expected argument types:");
        for (const [name, spec] of Object.entries(props)) {
            const req = required.includes(name) ? " (required)" : "";
            const t = (spec && typeof spec === "object" && !Array.isArray(spec)) ? (spec.type ?? "any") : "any";
            lines.push(`  ${name}${req}: ${t}`);
        }
        lines.push("");
    }
    lines.push("Stop retrying with the same arguments. Fix the listed fields and try once more.");
    return lines.join("\n");
}

function buildCapMessage(toolName, attempts) {
    return [
        `Maximum retries reached for ${toolName} (attempt ${String(attempts)}).`,
        "Do not retry this tool call.",
        "Summarize what you tried to do and ask the user how to proceed.",
    ].join("\n");
}
```

- [ ] **Step 4: Add currentSessionKey tracking inside register()**

Inside `register(api)`, after `const latestUserMessages = new Map();` (around line 859), add:

```javascript
    let currentSessionKey = "";
```

In the `message_received` hook body (around line 1098), after `latestUserMessages.set(key, text);`, add:

```javascript
            currentSessionKey = key;
```

- [ ] **Step 5: Rewrite the flat tool execute() handler**

Find the execute handler inside the `for (const rt of discovered)` loop (around line 1043):

```javascript
                        async execute(_toolCallId, params) {
                            await ensureConnected();
                            try {
                                const coercedParams = coerceFlatToolParams(params, rt.inputSchema);
                                const result = await mcpManager.callTool(rt.namespacedName, coercedParams);
                                const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
                                return {
                                    content: [{ type: "text", text }],
                                    details: { server: rt.serverName, tool: rt.originalName, params: coercedParams, result },
                                };
                            }
                            catch (err) {
                                const message = err instanceof Error ? err.message : String(err);
                                return {
                                    content: [{ type: "text", text: `Error calling ${rt.namespacedName}: ${message}` }],
                                    details: { server: rt.serverName, tool: rt.originalName, error: message },
                                };
                            }
                        },
```

Replace with:

```javascript
                        async execute(_toolCallId, params) {
                            await ensureConnected();
                            const sessionKey = currentSessionKey;
                            const toolSlug = rt.namespacedName.replace(/__/g, "_").slice(0, 60);
                            const thresholds = getRetryThresholds();
                            const retryState = await readRetryState(sessionKey, toolSlug);
                            const attempts = (retryState?.attempts ?? 0) + 1;
                            // Tier 2: hard cap — stop before even calling the gateway
                            if (attempts > thresholds.capAt) {
                                await clearRetryState(sessionKey, toolSlug);
                                return {
                                    content: [{ type: "text", text: buildCapMessage(rt.namespacedName, attempts) }],
                                    details: { server: rt.serverName, tool: rt.originalName, capped: true },
                                };
                            }
                            try {
                                const coercedParams = coerceFlatToolParams(params, rt.inputSchema);
                                const result = await mcpManager.callTool(rt.namespacedName, coercedParams);
                                // Success: clear retry state
                                await clearRetryState(sessionKey, toolSlug);
                                const rawText = typeof result === "string" ? result : JSON.stringify(result, null, 2);
                                return {
                                    content: [{ type: "text", text: rawText }],
                                    details: { server: rt.serverName, tool: rt.originalName, params: coercedParams, result },
                                };
                            }
                            catch (err) {
                                const message = err instanceof Error ? err.message : String(err);
                                await writeRetryState(sessionKey, toolSlug, { attempts, lastError: message });
                                // Tier 1: feedback injection
                                if (attempts >= thresholds.feedbackAt) {
                                    return {
                                        content: [{ type: "text", text: buildFeedbackMessage(rt.namespacedName, attempts, thresholds.capAt, message, rt.inputSchema) }],
                                        details: { server: rt.serverName, tool: rt.originalName, error: message, attempt: attempts },
                                    };
                                }
                                // Tier 0: pass error through normally (silent repair attempt)
                                return {
                                    content: [{ type: "text", text: `Error calling ${rt.namespacedName}: ${message}` }],
                                    details: { server: rt.serverName, tool: rt.originalName, error: message },
                                };
                            }
                        },
```

- [ ] **Step 6: Run test to verify it passes**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_retry_tier_logic -v
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

```
pytest tests/test_openclaw_mcp_bridge_contract.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```
git add tests/test_openclaw_mcp_bridge_contract.py openclaw/extensions/openclaw-mcp-bridge/dist/index.js
git commit -m "feat(bridge): add tiered retry budget with feedback injection for flat tool handlers"
```

---

## Task 7: Layer 3 — Response truncation

**Context:** Add `truncateToolResult()` that applies tool-specific and global truncation before the model sees the result. Handles `list_workflows` (filter to `mcp-api/*` only), search tools (cap at 3 results, truncate descriptions), and a global char cap (4000 for cloud, 2000 for GGUF). Wire it into the flat tool execute handler (replacing the bare `rawText` return from Task 6).

**Files:**
- Test: `tests/test_openclaw_mcp_bridge_contract.py`
- Modify: `openclaw/extensions/openclaw-mcp-bridge/dist/index.js`

- [ ] **Step 1: Write the failing contract test**

Add to `tests/test_openclaw_mcp_bridge_contract.py`:

```python
def test_mcp_bridge_response_truncation():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    assert "function isSearchTool(toolName)" in text
    assert "function truncateToolResult(text, toolName)" in text
    assert 'startsWith("mcp-api/")' in text
    assert "non-runnable workflow files omitted" in text
    assert "RESPONSE_CAP_CLOUD" in text
    assert "RESPONSE_CAP_GGUF" in text
    # Wired into flat tool handler
    assert "truncateToolResult(rawText, rt.namespacedName)" in text
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_response_truncation -v
```

Expected: FAIL.

- [ ] **Step 3: Add truncation functions to dist/index.js**

Insert these immediately before the `function register(api)` declaration (after the `IS_LOCAL_GGUF = false` line):

```javascript
// ---------------------------------------------------------------------------
// Response truncation — applied to all flat tool results before returning
// ---------------------------------------------------------------------------
const RESPONSE_CAP_CLOUD = 4000;
const RESPONSE_CAP_GGUF = 2000;
const SEARCH_MAX_ITEMS = 3;
const SEARCH_DESC_CLOUD = 200;
const SEARCH_DESC_GGUF = 150;

function isSearchTool(toolName) {
    const lower = toolName.toLowerCase();
    return (
        lower.includes("search") ||
        lower.includes("duckduckgo") ||
        lower.includes("tavily") ||
        (lower.includes("n8n") && (lower.includes("list") || lower.includes("search")))
    );
}

function truncateToolResult(text, toolName) {
    if (typeof text !== "string") {
        return String(text ?? "");
    }
    const cap = IS_LOCAL_GGUF ? RESPONSE_CAP_GGUF : RESPONSE_CAP_CLOUD;
    const descLen = IS_LOCAL_GGUF ? SEARCH_DESC_GGUF : SEARCH_DESC_CLOUD;
    let parsed;
    try {
        parsed = JSON.parse(text);
    }
    catch {
        // Not JSON — apply global cap only
        return text.length > cap ? `${text.slice(0, cap - 40)}\u2026[${text.length - cap} chars omitted]` : text;
    }
    // list_workflows: filter to mcp-api/* only
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && Array.isArray(parsed.workflow_files)) {
        const runnable = parsed.workflow_files.filter((w) => typeof w?.id === "string" && w.id.startsWith("mcp-api/"));
        const omitted = parsed.workflow_files.length - runnable.length;
        const out = { ...parsed, workflow_files: runnable };
        if (omitted > 0) {
            out._note = `${String(omitted)} non-runnable workflow files omitted (use workflow_id from mcp-api/* only)`;
        }
        text = JSON.stringify(out, null, 2);
    }
    // Search tools: cap results and truncate descriptions
    else if (isSearchTool(toolName) && parsed !== null) {
        const truncateDesc = (item) => {
            if (!item || typeof item !== "object" || Array.isArray(item)) {
                return item;
            }
            const out = { ...item };
            for (const field of ["description", "snippet", "text", "content", "body", "summary"]) {
                if (typeof out[field] === "string" && out[field].length > descLen) {
                    out[field] = `${out[field].slice(0, descLen)}\u2026`;
                }
            }
            return out;
        };
        const truncateList = (arr) => {
            if (!Array.isArray(arr)) {
                return arr;
            }
            const limited = arr.slice(0, SEARCH_MAX_ITEMS).map(truncateDesc);
            if (arr.length > SEARCH_MAX_ITEMS) {
                limited.push({ _note: `${String(arr.length - SEARCH_MAX_ITEMS)} more results omitted` });
            }
            return limited;
        };
        if (Array.isArray(parsed)) {
            parsed = truncateList(parsed);
        } else if (parsed && typeof parsed === "object") {
            for (const key of ["results", "items", "hits", "data"]) {
                if (Array.isArray(parsed[key])) {
                    parsed[key] = truncateList(parsed[key]);
                    break;
                }
            }
        }
        text = JSON.stringify(parsed, null, 2);
    }
    // Global cap
    if (text.length > cap) {
        text = `${text.slice(0, cap - 40)}\u2026[${text.length - cap} chars omitted]`;
    }
    return text;
}
```

- [ ] **Step 4: Wire truncateToolResult into the flat tool execute handler**

In the execute handler added in Task 6, find:

```javascript
                                const rawText = typeof result === "string" ? result : JSON.stringify(result, null, 2);
                                return {
                                    content: [{ type: "text", text: rawText }],
```

Replace with:

```javascript
                                const rawText = typeof result === "string" ? result : JSON.stringify(result, null, 2);
                                const text = truncateToolResult(rawText, rt.namespacedName);
                                return {
                                    content: [{ type: "text", text }],
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_openclaw_mcp_bridge_contract.py::test_mcp_bridge_response_truncation -v
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```
pytest tests/test_openclaw_mcp_bridge_contract.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add tests/test_openclaw_mcp_bridge_contract.py openclaw/extensions/openclaw-mcp-bridge/dist/index.js
git commit -m "feat(bridge): add response truncation for list_workflows, search tools, and global cap"
```

---

## Task 8: Layer 4 — Bootstrap compression

**Context:** TOOLS.md is 3668 raw chars and gets 24% cut at injection (per-file limit is 3000). HEARTBEAT.md is 100% cut (total budget exhausted). Fix: compress TOOLS.md to ≤1400 chars, convert HEARTBEAT.md to a minimal stub, and raise `OPENCLAW_BOOTSTRAP_TOTAL_MAX_CHARS` from 8000 to 12000.

**Files:**
- Modify: `openclaw/workspace/TOOLS.md`
- Modify: `openclaw/workspace/HEARTBEAT.md.example`
- Modify: `.env` (root)

- [ ] **Step 1: Verify current TOOLS.md length**

```
wc -c C:/dev/AI-toolkit/openclaw/workspace/TOOLS.md
```

Expected: around 3668 chars. Note the current content — you'll replace it entirely.

- [ ] **Step 2: Replace TOOLS.md with compressed version**

Write the following content to `openclaw/workspace/TOOLS.md` (replaces existing content entirely):

```markdown
# TOOLS.md

**MCP (primary):** One gateway URL: `servers.gateway` → `http://mcp-gateway:8811/mcp`. Use flat `gateway__...` tools first. Use `gateway__call` only as fallback with raw inner `tool` plus `args`. Never use `gateway__gateway__...`.

**Search & web research:** Prefer `gateway__tavily__tavily_search`. `gateway__duckduckgo__search` is the backup. Do not use native `web_search`.

**Built-in browser:** Denied in merged `openclaw.json`. No Playwright MCP in this stack.

**ComfyUI pre-built runnable workflows (use these first):**

| workflow_id | Media type | Key inputs |
|-------------|-----------|------------|
| `mcp-api/generate_video` | Video (LTX-2.3, 9:16) | `prompt`, `width` (576), `height` (1024), `frames` (121), `fps` (24) |
| `mcp-api/generate_song` | Audio (ACE-Step v1) | `tags` (required), `lyrics` (required) |
| `mcp-api/generate_image` | Image | `prompt` (required) |

`save_workflow` writes UI-format JSON — NOT runnable. Write API-format JSON to `data/comfyui-storage/ComfyUI/user/default/workflows/mcp-api/<id>.json` to persist a new runnable workflow.

**Files and shell:** Use `read`, `edit`, and `exec` per runtime for paths allowed in this workspace.

**Core services:**

| Service | Base |
|--------|------|
| Model Gateway | `http://model-gateway:11435/v1` |
| MCP Gateway | `http://mcp-gateway:8811/mcp` |
| Dashboard | `http://dashboard:8080` |
| ComfyUI | `http://comfyui:8188` |
| n8n | `http://n8n:5678` |
| OpenClaw UI | `http://openclaw-gateway:6680` |

**Discord:** `message` with `to: "channel:<id>"`, respect per-message size limits.

**ComfyUI model pulls:** Use `gateway__pull_comfyui_models` or `gateway__call` with `tool: "pull_comfyui_models"`. Full runbook in `agents/stack-ops.md`.
```

- [ ] **Step 3: Verify compressed TOOLS.md is under 1400 chars**

```
wc -c C:/dev/AI-toolkit/openclaw/workspace/TOOLS.md
```

Expected: ≤1400 chars.

- [ ] **Step 4: Replace HEARTBEAT.md.example with stub**

Write the following content to `openclaw/workspace/HEARTBEAT.md.example` (replaces existing content):

```markdown
<!-- Copy to HEARTBEAT.md -->

# HEARTBEAT.md

Current stack health is available on demand — call `gateway__get_services` or read `agents/stack-ops.md`. Do not add recurring checklist items here unless the operator explicitly asks.
```

- [ ] **Step 5: Add bootstrap total budget to root .env**

Open `.env` in the repo root. Find the existing `OPENCLAW_COMPACTION_MODE=safeguard` line (or any OPENCLAW_ block). Add after it:

```env
OPENCLAW_BOOTSTRAP_TOTAL_MAX_CHARS=12000
```

Note: `OPENCLAW_BOOTSTRAP_MAX_CHARS` defaults to 3000 in `openclaw/scripts/merge_gateway_config.py` — no need to add it explicitly unless you want to lock it in.

- [ ] **Step 6: Verify the budget arithmetic**

With the new values, confirm all bootstrap files fit under 12000 chars total:

```bash
wc -c C:/dev/AI-toolkit/openclaw/workspace/AGENTS.md \
       C:/dev/AI-toolkit/openclaw/workspace/SOUL.md \
       C:/dev/AI-toolkit/openclaw/workspace/TOOLS.md \
       C:/dev/AI-toolkit/openclaw/workspace/MEMORY.md
```

Expected total: ≤5000 chars (comfortably under 12000, leaving budget for USER.md and HEARTBEAT.md).

- [ ] **Step 7: Re-run the config sync to apply the new bootstrap total**

```bash
docker compose run --rm openclaw-config-sync
```

If the service name differs, check with `docker compose ps`. This regenerates `data/openclaw/openclaw.json` with the updated `bootstrapTotalMaxChars`.

- [ ] **Step 8: Commit**

```
git add openclaw/workspace/TOOLS.md openclaw/workspace/HEARTBEAT.md.example .env
git commit -m "feat(bootstrap): compress TOOLS.md and raise bootstrap total budget to 12000 chars"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** L1a (Task 1), L1b (Task 2), L1c (Task 3), L5 (Task 4), L2 state utils (Task 5), L2 tier logic (Task 6), L3 truncation (Task 7), L4 bootstrap (Task 8). All six spec layers covered.
- [x] **Placeholders:** None. Every step has actual code or exact commands.
- [x] **Type consistency:** `coerceObjectField` defined in Task 2, called in `coerceFlatToolValue` in Task 2. `IS_LOCAL_GGUF` declared in Task 4, used in Task 6 (`getRetryThresholds`) and Task 7 (`truncateToolResult`). `readRetryState`/`writeRetryState`/`clearRetryState` defined in Task 5, used in Task 6. `truncateToolResult` defined in Task 7, wired in Task 7 Step 4. `currentSessionKey` declared in Task 6, updated in `message_received` hook in Task 6, read in execute handler in Task 6. All consistent.
- [x] **Ordering:** Tasks 1–3 are independent of each other and of Tasks 4–7. Task 6 depends on Tasks 4 and 5 (reads `IS_LOCAL_GGUF` and retry state functions). Task 7 depends on Task 4 (reads `IS_LOCAL_GGUF`). Task 8 is fully independent. Order is safe.
