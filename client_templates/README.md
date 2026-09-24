# AI Gateway Client Integration Templates

This directory provides production-ready configuration manifests and code examples to connect developer tools, CLI agents, and SDKs directly to the **Minimal Local AI Gateway**.

Crucially, **no custom headers or proprietary metadata are required**. Clients connect using standard base URL overrides and Bearer virtual keys. Multi-turn task correlation, branch sniffing, secret redaction, and Cost Per Success (CPS) tracking occur completely transparently in transient gateway memory.

*(Note: Cursor IDE configuration is intentionally omitted per project instructions).*

---

## 1. Claude Code CLI (`~/.claude/config.json`)

To route Claude Code traffic through the gateway:

### Option A: Configuration File
Place in `~/.claude/config.json` (or `.claude/config.json` in your project root):

```json
{
  "api_base": "http://localhost:4000/v1",
  "api_key": "sk-agent-developer",
  "default_model": "claude-3-5-sonnet",
  "temperature": 0.2,
  "max_tokens": 4096
}
```

### Option B: Environment Variables
Alternatively, source [`claude_env.sh`](./claude_env.sh) before invoking the CLI:
```bash
source client_templates/claude_env.sh
claude
```

---

## 2. Standard OpenAI Python SDK

Connect any Python agent framework or script with zero changes to business logic:

```python
from openai import OpenAI

# 1. Point client to the local gateway proxy
client = OpenAI(
    base_url="http://localhost:4000/v1",
    api_key="sk-agent-developer",
)

# 2. Standard chat completion (streaming or non-streaming)
response = client.chat.completions.create(
    model="mock-model", # or "gpt-4o", "claude-3-5-sonnet"
    messages=[
        {"role": "system", "content": "You are a software engineering assistant."},
        {"role": "user", "content": "Implement Redis distributed lock in Python."}
    ],
    temperature=0.2,
)

print(response.choices[0].message.content)
```

Run the runnable example:
```bash
python3 client_templates/openai_sdk_example.py
```

---

## 3. Model Context Protocol (MCP) Server Configuration

Coding agents interact with standard MCP servers normally. The gateway inspects Git branch tool calls emitted by MCP servers (e.g. `@modelcontextprotocol/server-git`) in RAM to register ephemeral branch hashes in Redis.

Save as `mcp_servers.json` (or inside `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "git": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-git"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/mako/Mukesh_Workspace"]
    }
  }
}
```

---

## 4. Generic Agent Frameworks (Aider, AutoGen, CrewAI, LangChain)

For any tool supporting standard OpenAI environment variables, simply source [`generic_agent_env.sh`](./generic_agent_env.sh):

```bash
source client_templates/generic_agent_env.sh
```

Exported variables:
- `OPENAI_BASE_URL="http://localhost:4000/v1"`
- `OPENAI_API_BASE="http://localhost:4000/v1"`
- `OPENAI_API_KEY="sk-agent-developer"`
- `OPENAI_MODEL="mock-model"`

---

## 5. Gateway Key & Role Reference

| Virtual Key | Role | Model Access | Daily Spend Cap |
| :--- | :--- | :--- | :--- |
| `sk-agent-developer` | `developer` | `gpt-4o`, `claude-3-5-sonnet`, `mock-model` | $5.00 / day |
| `sk-agent-intern-poc` | `intern` | `gpt-4o-mini`, `mock-model` | $1.00 / day |
| `sk-enterprise-master-secret-key-2026` | `admin` | All endpoints (`/key/generate`, `/key/info`, `/ui`) | Unlimited |
