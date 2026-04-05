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
    if (!text.startsWith("{")) {
        text = `{${text}}`;
    }
    let parsed;
    try {
        parsed = JSON.parse(text);
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`args JSON parse failed: ${msg}`);
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("args must resolve to an object");
    }
    return parsed;
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
    const mcpManager = new MCPManager(toManagerConfig(config));
    // Register a factory for each configured server's tools.
    // The factory connects lazily on first tool call.
    // Uses a promise guard to prevent concurrent connectAll() calls from
    // racing and corrupting the session (double-init → "invalid during
    // session initialization" errors from the MCP gateway).
    let connected = false;
    let connectingPromise = null;
    const ensureConnected = async () => {
        if (connected)
            return;
        if (connectingPromise !== null)
            return connectingPromise;
        connectingPromise = mcpManager.connectAll().then(() => {
            connected = true;
        }).finally(() => {
            connectingPromise = null;
        });
        return connectingPromise;
    };
    // Register a proxy tool per configured server.
    // Each tool connects lazily and forwards calls to the remote MCP server.
    for (const [serverName, serverConfig] of Object.entries(config.servers)) {
        if (serverConfig.enabled === false)
            continue;
        const prefix = serverConfig.toolPrefix ?? serverName;
        api.registerTool({
            name: `${prefix}__call`,
            label: `MCP: ${serverName}`,
            description: `Call a tool on MCP server "${serverName}" (${serverConfig.url}). Pass tool name and arguments to invoke any tool on this server.`,
            parameters: Type.Object({
                tool: Type.String({ description: "The tool name to call on this server" }),
                args: Type.Optional(Type.Union([
                    Type.Record(Type.String(), Type.Unknown(), { description: "Arguments to pass to the tool" }),
                    Type.String({ description: "JSON object string of arguments; accepted for models that emit stringified tool args" }),
                ])),
            }),
            async execute(_toolCallId, params) {
                await ensureConnected();
                const toolName = params.tool;
                const args = coerceToolArgs(params.args);
                try {
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
                    return {
                        content: [{ type: "text", text: `Error calling ${prefix}__${toolName}: ${message}` }],
                        details: { server: serverName, tool: toolName, error: message },
                    };
                }
            },
        });
        api.logger.info(`mcp-client: registered proxy tool ${prefix}__call for server "${serverName}"`);
    }
    // Register each discovered MCP tool as its own OpenClaw tool (e.g. gateway__duckduckgo__search).
    // Upstream only registered *ServerName*__call; models often emit the namespaced MCP id, which hit Tool not found.
    let flatToolsRegistered = false;
    /** Avoid infinite hooks if gateway never exposes tools. */
    let flatToolsRegistrationAttempts = 0;
    const MAX_FLAT_REGISTRATION_ATTEMPTS = 24;
    /** Delay helper */
    const _delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const registerFlatMcpTools = async () => {
        if (flatToolsRegistered) {
            return;
        }
        try {
            await ensureConnected();
            // On first attempt after connection, refresh tools from the gateway
            // to pick up servers that loaded after the initial connectAll().
            if (flatToolsRegistrationAttempts > 0) {
                try {
                    await mcpManager.refreshTools();
                } catch (_refreshErr) {
                    // Refresh failed — fall through to check registry as-is
                }
            }
            const discovered = mcpManager.getRegisteredTools();
            if (discovered.length === 0) {
                flatToolsRegistrationAttempts += 1;
                if (flatToolsRegistrationAttempts >= MAX_FLAT_REGISTRATION_ATTEMPTS) {
                    api.logger.warn("[mcp-bridge] registerFlatMcpTools: giving up after " +
                        String(MAX_FLAT_REGISTRATION_ATTEMPTS) +
                        " attempts with 0 tools — check mcp-gateway and data/mcp/servers.txt (include comfyui). " +
                        "Use gateway__call with tool names from the gateway until flat tools appear.");
                    flatToolsRegistered = true;
                    return;
                }
                api.logger.warn("[mcp-bridge] registerFlatMcpTools: 0 tools in registry (attempt " +
                    String(flatToolsRegistrationAttempts) + "/" + String(MAX_FLAT_REGISTRATION_ATTEMPTS) +
                    "). Retrying in 5s — MCP gateway may still be loading servers.");
                // Schedule a timed retry instead of waiting for the next hook
                setTimeout(() => { registerFlatMcpTools().catch(() => {}); }, 5000);
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
    // Eager: kick off flat tool discovery synchronously (as a floating promise).
    // Hooks may not fire on all OpenClaw versions; calling directly ensures discovery runs.
    api.logger.info("[mcp-bridge] starting eager flat tool discovery");
    registerFlatMcpTools().then(() => {
        api.logger.info("[mcp-bridge] eager discovery done, registered=" + String(flatToolsRegistered));
    }).catch((err) => {
        api.logger.warn("[mcp-bridge] eager discovery error: " + String(err));
    });
    // Register shutdown hook
    api.registerHook("gateway_stop", async () => {
        if (connected) {
            await mcpManager.disconnectAll();
        }
    }, { name: "mcp-client-shutdown", description: "Disconnect all MCP servers" });
    // Register schema injection hook (injects MCP tool schemas into agent context)
    if (config.injectSchemas !== false) {
        api.on("before_prompt_build", async () => {
            try {
                await ensureConnected();
                const allSchemas = [];
                for (const [serverName, serverConfig] of Object.entries(config.servers)) {
                    if (serverConfig.enabled === false)
                        continue;
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
                if (allSchemas.length > 0) {
                    const firstServerName = Object.keys(config.servers)[0];
                    const firstConfig = config.servers[firstServerName];
                    const prefix = firstConfig?.toolPrefix ?? firstServerName;
                    return {
                        appendSystemContext: `\n\n## MCP Tools Available\n\nThe following tools are available via MCP servers. Use the flat \`gateway__...\` tools when available. If you use \`${prefix}__call\`, the inner \`tool\` value must be the raw tool name without a \`gateway__\` prefix.\n\nFor unattended or cron runs: do not emit progress chatter such as "Let me check..." or "Fetching more...". Keep assistant text empty while calling tools, then emit exactly one final non-empty assistant message.\n\n${allSchemas.join("\n\n")}`,
                    };
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
// Manager layer
export { MCPManager } from "./manager/mcp-manager.js";
export { ToolRegistry } from "./manager/tool-registry.js";
// Transport layer
export { StreamableHTTPTransport } from "./transport/streamable-http.js";
export { StdioTransport } from "./transport/stdio.js";
export { SSEParser, parseSSEStream } from "./transport/sse-parser.js";
// Config and types
export { configSchema } from "./config-schema.js";
export { MCPError } from "./types.js";
//# sourceMappingURL=index.js.map
