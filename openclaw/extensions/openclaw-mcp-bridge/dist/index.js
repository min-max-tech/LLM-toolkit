/**
 * Plugin entry point for the OpenClaw MCP client plugin.
 *
 * Implements the OpenClaw plugin SDK contract: exports a default object
 * with a `register(api)` function that registers MCP tools via
 * `api.registerTool()`.
 *
 * @see SPEC.md section 6.4 for the plugin entry point specification.
 */
import { Type } from "@sinclair/typebox";
import { MCPManager } from "./manager/mcp-manager.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
/**
 * Convert a ConfigSchemaType to the MCPManagerConfig shape expected by MCPManager.
 *
 * @param config - The plugin configuration from OpenClaw.
 * @returns An MCPManagerConfig ready for the MCPManager constructor.
 */
function toManagerConfig(config) {
    return {
        servers: config.servers,
        toolDiscoveryInterval: config.toolDiscoveryInterval,
        maxConcurrentServers: config.maxConcurrentServers,
        debug: config.debug,
    };
}

function resolveProxyToolName(mcpManager, prefix, rawToolName) {
    const toolName = typeof rawToolName === "string" ? rawToolName.trim() : "";
    const candidates = [];
    const addCandidate = (candidate) => {
        if (typeof candidate !== "string" || candidate.length === 0) {
            return;
        }
        if (!candidates.includes(candidate)) {
            candidates.push(candidate);
        }
    };
    if (toolName.startsWith(`${prefix}__`)) {
        addCandidate(toolName);
    }
    addCandidate(`${prefix}__${toolName}`);
    if (toolName.includes("__")) {
        addCandidate(`${prefix}__${toolName.replace(/__/g, "_")}`);
        const parts = toolName.split("__").filter((part) => part.length > 0);
        if (parts.length > 1) {
            const withoutFirst = parts.slice(1).join("__");
            addCandidate(`${prefix}__${withoutFirst}`);
            addCandidate(`${prefix}__${withoutFirst.replace(/__/g, "_")}`);
            addCandidate(`${prefix}__${parts[parts.length - 1]}`);
        }
    }
    const registered = new Set(mcpManager.getRegisteredTools().map((tool) => tool.namespacedName));
    for (const candidate of candidates) {
        if (registered.has(candidate)) {
            return candidate;
        }
    }
    return candidates[0] ?? `${prefix}__${toolName}`;
}

function toFlatToolParametersSchema(rt) {
    const schema = rt?.inputSchema;
    if (schema && typeof schema === "object" && !Array.isArray(schema)) {
        return schema;
    }
    return Type.Record(Type.String(), Type.Unknown(), {
        description: "Arguments for this MCP tool (see injected MCP tool list).",
    });
}

function coerceToolArgs(raw) {
    if (raw == null) {
        return {};
    }
    if (typeof raw === "object" && !Array.isArray(raw)) {
        return raw;
    }
    if (typeof raw !== "string") {
        throw new Error("args must be an object or JSON object string");
    }
    let text = raw.trim();
    if (!text) {
        return {};
    }
    text = text
        .replaceAll('<|"|>', '"')
        .replaceAll("<|'|>", "'")
        .replaceAll("<|`|>", "`")
        .replaceAll("<|\\n|>", "\n")
        .replace(/<\|(.)\|>/g, "$1");
    // Strip leading/trailing quotes from models that double-stringify args
    if ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"))) {
        try {
            const inner = JSON.parse(text);
            if (typeof inner === "string") {
                text = inner.trim();
            }
        }
        catch { /* not a quoted string, continue with original */ }
    }
    // Strip a stray leading quote Gemma emits before { (e.g. <|"|>{...} → "{..." → {...)
    if (text.startsWith('"') && text.length > 1 && (text[1] === '{' || text[1] === '[')) {
        text = text.slice(1);
    }
    if (!text.startsWith("{")) {
        text = `{${text}}`;
    }
    let parsed;
    try {
        parsed = JSON.parse(text);
    }
    catch (err) {
        const repaired = text
            .replace(/\]\s*$/, "}")
            .replace(/,\s*}/g, "}")
            .replace(/([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)/g, '$1"$2"$3')
            .replace(/:\s*'([^']*)'/g, ': "$1"')
            .replace(/\bTrue\b/g, "true")
            .replace(/\bFalse\b/g, "false")
            .replace(/\bNone\b/g, "null");
        const balanced = repaired.endsWith("}") ? repaired : `${repaired}}`;
        try {
            parsed = JSON.parse(balanced);
        }
        catch (_repairErr) {
            const msg = err instanceof Error ? err.message : String(err);
            throw new Error(`args JSON parse failed: ${msg}`);
        }
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("args must resolve to an object");
    }
    return parsed;
}

function coerceToolName(raw, prefix) {
    if (typeof raw === "string" && raw.trim()) {
        return raw.trim();
    }
    if (typeof raw === "object" && raw && !Array.isArray(raw)) {
        const candidate = raw.tool ?? raw.toolName ?? raw.name ?? raw.namespacedTool;
        if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
        }
    }
    throw new Error(`missing required tool name for ${prefix}__call; provide "tool" with the raw MCP tool name or run ${prefix}__discover first`);
}

function compactToolMetadata(rt, includeSchema = false) {
    const schema = rt?.inputSchema && typeof rt.inputSchema === "object" && !Array.isArray(rt.inputSchema)
        ? rt.inputSchema
        : {};
    const properties = schema.properties && typeof schema.properties === "object" ? schema.properties : {};
    const required = Array.isArray(schema.required) ? new Set(schema.required) : new Set();
    const argumentsSummary = Object.entries(properties).map(([name, spec]) => ({
        name,
        required: required.has(name),
        type: spec?.type ?? "unknown",
        description: spec?.description ?? "",
    }));
    const metadata = {
        server: rt.serverName,
        tool: rt.originalName,
        namespacedTool: rt.namespacedName,
        description: rt.description ?? "",
        arguments: argumentsSummary,
    };
    if (includeSchema) {
        metadata.inputSchema = schema;
    }
    return metadata;
}

function buildSchemaContext(config, allSchemas, flatToolsEnabled) {
    if (allSchemas.length === 0) {
        return "";
    }
    const firstServerName = Object.keys(config.servers)[0];
    const firstConfig = config.servers[firstServerName];
    const prefix = firstConfig?.toolPrefix ?? firstServerName;
    const usage = flatToolsEnabled
        ? `Use the flat \`gateway__...\` tools when available. If you use \`${prefix}__call\`, the inner \`tool\` value must be the raw tool name without a \`gateway__\` prefix.`
        : `Use only \`${prefix}__call\`. The inner \`tool\` value must be the raw MCP tool name without a \`gateway__\` prefix.`;
    return `\n\n## MCP Tools Available\n\n${usage}\n\nFor unattended or cron runs: do not emit progress chatter such as "Let me check..." or "Fetching more...". Keep assistant text empty while calling tools, then emit exactly one final non-empty assistant message.\n\n${allSchemas.join("\n\n")}`;
}

// ---------------------------------------------------------------------------
// Plugin registration
// ---------------------------------------------------------------------------
/**
 * Register function called synchronously by OpenClaw's plugin runtime.
 *
 * Since MCP server connections are async but register() must be synchronous,
 * we register tool factories that lazily connect on first invocation.
 *
 * @param api - The OpenClaw plugin API.
 */
function register(api) {
    const config = api.pluginConfig;
    if (!config?.servers || Object.keys(config.servers).length === 0) {
        return;
    }

    const flatToolsEnabled = config.flatTools === true;
    const injectSchemasEnabled = config.injectSchemas !== false;
    const mcpManager = new MCPManager(toManagerConfig(config));

    let connected = false;
    let connectingPromise = null;
    const ensureConnected = async () => {
        if (connected) {
            return;
        }
        if (connectingPromise !== null) {
            return connectingPromise;
        }
        connectingPromise = mcpManager.connectAll().then(() => {
            connected = true;
        }).finally(() => {
            connectingPromise = null;
        });
        return connectingPromise;
    };

    for (const [serverName, serverConfig] of Object.entries(config.servers)) {
        if (serverConfig.enabled === false) {
            continue;
        }
        const prefix = serverConfig.toolPrefix ?? serverName;
        api.registerTool({
            name: `${prefix}__call`,
            label: `MCP: ${serverName}`,
            description: `Call a tool on MCP server "${serverName}" (${serverConfig.url}). Pass tool name and arguments to invoke any tool on this server.`,
            parameters: Type.Object({
                tool: Type.String({ description: `The raw MCP tool name to call on this server (e.g. "duckduckgo_web_search"). Run ${prefix}__discover first if unsure of the exact name.` }),
                args: Type.Optional(Type.Union([
                    Type.Record(Type.String(), Type.Unknown(), { description: "Arguments to pass to the tool" }),
                    Type.String({ description: "JSON object string of arguments; accepted for models that emit stringified tool args" }),
                ])),
            }),
            async execute(_toolCallId, params) {
                try {
                    await ensureConnected();
                    const toolName = coerceToolName(params, prefix);
                    const args = coerceToolArgs(params.args);
                    const resolvedToolName = resolveProxyToolName(mcpManager, prefix, toolName);
                    if (resolvedToolName !== `${prefix}__${toolName}`) {
                        api.logger.info(`mcp-client: normalized proxy tool "${toolName}" -> "${resolvedToolName}"`);
                    }
                    const result = await mcpManager.callTool(resolvedToolName, args);
                    const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
                    return {
                        content: [{ type: "text", text }],
                        details: { server: serverName, tool: toolName, resolvedTool: resolvedToolName, result },
                    };
                }
                catch (err) {
                    const message = err instanceof Error ? err.message : String(err);
                    const example = `Example: ${prefix}__call({"tool": "duckduckgo_web_search", "args": {"query": "your search"}})`;
                    if (message.includes("missing required tool name")) {
                        // Auto-discover: return tool list instead of a dead-end error so the model can pick the right tool
                        const discovered = mcpManager.getRegisteredTools()
                            .filter((t) => t.serverName === serverName)
                            .slice(0, 12)
                            .map((t) => compactToolMetadata(t, false));
                        const toolListText = discovered.length > 0
                            ? JSON.stringify({ server: serverName, count: discovered.length, tools: discovered }, null, 2)
                            : `No tools found on server "${serverName}".`;
                        return {
                            content: [{ type: "text", text: `You must provide a "tool" parameter. ${example}\n\nAvailable tools on "${serverName}":\n${toolListText}` }],
                            details: { server: serverName, autoDiscovered: true, count: discovered.length },
                        };
                    }
                    const hint = message.includes("JSON parse failed")
                        ? `The "args" value must be valid JSON (use standard double quotes, not escape tokens). ${example}`
                        : message;
                    return {
                        content: [{ type: "text", text: `Error: ${hint}` }],
                        details: { server: serverName, tool: params?.tool ?? "<missing>", error: message },
                    };
                }
            },
        });
        api.logger.info(`mcp-client: registered proxy tool ${prefix}__call for server "${serverName}"`);
        api.registerTool({
            name: `${prefix}__discover`,
            label: `MCP Discover: ${serverName}`,
            description: `Discover tools on MCP server "${serverName}" with a compact result. Use this before ${prefix}__call when you do not know the exact tool name.`,
            parameters: Type.Object({
                query: Type.Optional(Type.String({ description: "Optional substring filter for tool name or description" })),
                limit: Type.Optional(Type.Number({ description: "Maximum number of tools to return", default: 12 })),
                includeSchema: Type.Optional(Type.Boolean({ description: "Include the full JSON schema for matching tools", default: false })),
            }),
            async execute(_toolCallId, params) {
                await ensureConnected();
                const query = typeof params.query === "string" ? params.query.trim().toLowerCase() : "";
                const limit = Number.isFinite(params.limit) ? Math.max(1, Math.min(50, Math.trunc(params.limit))) : 12;
                const includeSchema = params.includeSchema === true;
                const discovered = mcpManager.getRegisteredTools()
                    .filter((tool) => tool.serverName === serverName)
                    .filter((tool) => {
                    if (!query) {
                        return true;
                    }
                    const haystack = `${tool.originalName} ${tool.namespacedName} ${tool.description ?? ""}`.toLowerCase();
                    return haystack.includes(query);
                })
                    .slice(0, limit)
                    .map((tool) => compactToolMetadata(tool, includeSchema));
                const text = discovered.length > 0
                    ? JSON.stringify({ server: serverName, count: discovered.length, tools: discovered }, null, 2)
                    : JSON.stringify({
                        server: serverName,
                        count: 0,
                        tools: [],
                        hint: `No tools matched. Retry ${prefix}__discover with a broader query or omit query entirely.`,
                    }, null, 2);
                return {
                    content: [{ type: "text", text }],
                    details: { server: serverName, query, count: discovered.length, tools: discovered },
                };
            },
        });
        api.logger.info(`mcp-client: registered discovery tool ${prefix}__discover for server "${serverName}"`);
    }

    if (!flatToolsEnabled) {
        api.logger.info("[mcp-bridge] flatTools disabled - only gateway__call registered (set flatTools: true to enable eager discovery)");
    }

    if (flatToolsEnabled) {
        let flatToolsRegistered = false;
        let flatToolsRegistrationAttempts = 0;
        const MAX_FLAT_REGISTRATION_ATTEMPTS = 24;
        const registerFlatMcpTools = async () => {
            if (flatToolsRegistered) {
                return;
            }
            try {
                await ensureConnected();
                if (flatToolsRegistrationAttempts > 0) {
                    try {
                        await mcpManager.refreshTools();
                    }
                    catch (_refreshErr) {
                        // Refresh failed; fall through to check registry as-is.
                    }
                }
                const discovered = mcpManager.getRegisteredTools();
                if (discovered.length === 0) {
                    flatToolsRegistrationAttempts += 1;
                    if (flatToolsRegistrationAttempts >= MAX_FLAT_REGISTRATION_ATTEMPTS) {
                        api.logger.warn("[mcp-bridge] registerFlatMcpTools: giving up after " +
                            String(MAX_FLAT_REGISTRATION_ATTEMPTS) +
                            " attempts with 0 tools - check mcp-gateway and data/mcp/servers.txt (include comfyui). " +
                            "Use gateway__call with tool names from the gateway until flat tools appear.");
                        flatToolsRegistered = true;
                        return;
                    }
                    api.logger.warn("[mcp-bridge] registerFlatMcpTools: 0 tools in registry (attempt " +
                        String(flatToolsRegistrationAttempts) + "/" + String(MAX_FLAT_REGISTRATION_ATTEMPTS) +
                        "). Retrying in 5s - MCP gateway may still be loading servers.");
                    setTimeout(() => { registerFlatMcpTools().catch(() => { }); }, 5000);
                    return;
                }
                for (const rt of discovered) {
                    const srvCfg = config.servers[rt.serverName];
                    const pfx = srvCfg?.toolPrefix ?? rt.serverName;
                    api.registerTool({
                        name: rt.namespacedName,
                        label: `MCP ${rt.serverName}: ${rt.originalName}`,
                        description: `${rt.description ?? ""}\n\nSame as \`${pfx}__call\` with tool "${rt.originalName}" and args for parameters.`,
                        parameters: toFlatToolParametersSchema(rt),
                        async execute(_toolCallId, params) {
                            await ensureConnected();
                            try {
                                const result = await mcpManager.callTool(rt.namespacedName, params);
                                const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
                                return {
                                    content: [{ type: "text", text }],
                                    details: { server: rt.serverName, tool: rt.originalName, result },
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
                    });
                    api.logger.info(`mcp-client: registered flat tool ${rt.namespacedName}`);
                }
                flatToolsRegistered = true;
            }
            catch (err) {
                api.logger.warn("[mcp-bridge] registerFlatMcpTools failed:", err);
            }
        };

        const flatToolsHook = async () => {
            await registerFlatMcpTools();
        };
        api.registerHook("gateway_start", flatToolsHook, { name: "mcp-flat-tools-gateway", description: "Expose namespaced MCP tools as OpenClaw tools" });
        api.registerHook("session_start", flatToolsHook, { name: "mcp-flat-tools-session", description: "Fallback if gateway_start is unavailable" });
        api.logger.info("[mcp-bridge] starting eager flat tool discovery");
        registerFlatMcpTools().then(() => {
            api.logger.info("[mcp-bridge] eager discovery done, registered=" + String(flatToolsRegistered));
        }).catch((err) => {
            api.logger.warn("[mcp-bridge] eager discovery error: " + String(err));
        });
    }

    api.registerHook("gateway_stop", async () => {
        if (connected) {
            await mcpManager.disconnectAll();
        }
    }, { name: "mcp-client-shutdown", description: "Disconnect all MCP servers" });

    api.on("before_prompt_build", async () => {
        const firstServerName = Object.keys(config.servers)[0];
        const firstConfig = config.servers[firstServerName];
        const prefix = firstConfig?.toolPrefix ?? firstServerName;
        const context = [
            "## MCP Tool Contract",
            `Use \`${prefix}__call\` to execute MCP tools.`,
            `Use \`${prefix}__discover\` first when you do not know the exact tool name or arguments.`,
            `Inside \`${prefix}__call\`, pass the raw MCP tool name in \`tool\` without a \`${prefix}__\` prefix.`,
            `Example: \`${prefix}__call({\"tool\":\"list_workflows\",\"args\":{\"details\":false}})\`.`,
            "Do not assume unavailable tools exist; discover them or report the failure truthfully.",
        ].join("\n");
        return { appendSystemContext: `\n\n${context}` };
    }, { priority: 4 });

    if (injectSchemasEnabled) {
        let schemaContext = "";
        let schemaContextPromise = null;
        const loadSchemaContext = async () => {
            if (schemaContext) {
                return schemaContext;
            }
            if (schemaContextPromise !== null) {
                return schemaContextPromise;
            }
            schemaContextPromise = (async () => {
                await ensureConnected();
                const allSchemas = [];
                for (const [serverName, serverConfig] of Object.entries(config.servers)) {
                    if (serverConfig.enabled === false) {
                        continue;
                    }
                    try {
                        const tools = await mcpManager.listTools(serverName);
                        if (tools.length > 0) {
                            const formatted = tools.map((tool) => {
                                const props = tool.inputSchema?.properties;
                                const params = props
                                    ? Object.entries(props)
                                        .map(([name, schema]) => {
                                        const s = schema;
                                        const required = tool.inputSchema.required?.includes(name) ? " (required)" : "";
                                        const description = (s.description ?? s.type ?? "");
                                        return `  - **${name}**${required}: ${description}`;
                                    })
                                        .join("\n")
                                    : "  (no parameters)";
                                return `### ${tool.name}\n${tool.description ?? ""}\n\nParameters:\n${params}`;
                            }).join("\n\n");
                            allSchemas.push(`## MCP Server: ${serverName}\n\n${formatted}`);
                        }
                    }
                    catch (err) {
                        api.logger.warn(`[mcp-bridge] Failed to fetch schemas from ${serverName}:`, err);
                    }
                }
                return buildSchemaContext(config, allSchemas, flatToolsEnabled);
            })().then((context) => {
                schemaContext = context;
                return context;
            }).finally(() => {
                schemaContextPromise = null;
            });
            return schemaContextPromise;
        };

        api.on("before_prompt_build", async () => {
            try {
                const context = await loadSchemaContext();
                if (context) {
                    return { appendSystemContext: context };
                }
            }
            catch (error) {
                api.logger.warn("[mcp-bridge] Failed to inject MCP schemas:", error);
            }
            return {};
        }, { priority: 5 });
        api.logger.info("mcp-client: registered schema injection hook");
    }
}

/**
 * Standalone plugin object with an async initialize() method.
 *
 * Connects to all configured MCP servers eagerly, discovers tools,
 * and returns them as ToolDefinition objects with bound execute functions.
 *
 * @param context - The plugin context containing configuration.
 * @returns A PluginResult with tools, shutdown, and config-change callbacks.
 */
export const plugin = {
    async initialize(context) {
        const config = context.config;
        if (!config?.servers || Object.keys(config.servers).length === 0) {
            return { tools: [], onShutdown: async () => { } };
        }
        const mcpManager = new MCPManager(toManagerConfig(config));
        await mcpManager.connectAll();
        const buildTools = () => {
            const registeredTools = mcpManager.getRegisteredTools();
            return registeredTools.map((rt) => ({
                name: rt.namespacedName,
                description: rt.description,
                inputSchema: rt.inputSchema,
                execute: async (args) => {
                    return mcpManager.callTool(rt.namespacedName, args);
                },
            }));
        };
        const tools = buildTools();
        return {
            tools,
            onShutdown: async () => {
                await mcpManager.disconnectAll();
            },
            onConfigChange: async (newConfig) => {
                await mcpManager.reconcile(toManagerConfig(newConfig));
            },
        };
    },
};

// ---------------------------------------------------------------------------
// Default Export
// ---------------------------------------------------------------------------
export default { register };

// ---------------------------------------------------------------------------
// Re-exports for external consumers
// ---------------------------------------------------------------------------
export { MCPManager } from "./manager/mcp-manager.js";
export { ToolRegistry } from "./manager/tool-registry.js";
export { StreamableHTTPTransport } from "./transport/streamable-http.js";
export { StdioTransport } from "./transport/stdio.js";
export { SSEParser, parseSSEStream } from "./transport/sse-parser.js";
export { configSchema } from "./config-schema.js";
export { MCPError } from "./types.js";
//# sourceMappingURL=index.js.map
