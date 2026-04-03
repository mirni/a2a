# a2a-langchain

LangChain tool wrappers for the [A2A Commerce Platform](https://greenhelix.net) SDK.

## Installation

```bash
pip install a2a-langchain
```

## Quick Start

### Pre-built Tools

Use the 10 pre-built tool classes directly with any LangChain agent:

```python
from a2a_sdk import A2AClient
from a2a_langchain import A2AGetBalance, A2ADeposit, A2ASearchServices

client = A2AClient(base_url="https://api.greenhelix.net", api_key="a2a_...")

tools = [
    A2AGetBalance(client=client),
    A2ADeposit(client=client),
    A2ASearchServices(client=client),
]

# Pass tools to a LangChain agent
from langchain.agents import initialize_agent, AgentType
agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS)
result = agent.run("What is agent-1's balance?")
```

### Dynamic Toolkit

Load all tools (or a filtered subset) from the live catalog:

```python
from a2a_sdk import A2AClient
from a2a_langchain import A2AToolkit

client = A2AClient(base_url="https://api.greenhelix.net", api_key="a2a_...")

# All tools
toolkit = await A2AToolkit.from_client(client)

# Only billing + payments tools
toolkit = await A2AToolkit.from_client(client, services=["billing", "payments"])

tools = toolkit.get_tools()
```

### Dynamic Tool Factory

Build a single tool from a catalog entry:

```python
from a2a_langchain import create_tool

tool = create_tool(client, {
    "name": "get_balance",
    "description": "Get wallet balance",
    "input_schema": {
        "type": "object",
        "properties": {"agent_id": {"type": "string"}},
        "required": ["agent_id"],
    },
})
```

## Pre-built Tools

| Class | Tool Name | Description |
|---|---|---|
| `A2AGetBalance` | `get_balance` | Get wallet balance for an agent |
| `A2ADeposit` | `deposit` | Deposit credits into agent wallet |
| `A2ACreatePaymentIntent` | `create_intent` | Create a payment intent |
| `A2ACapturePayment` | `capture_intent` | Capture and settle a payment |
| `A2ACreateEscrow` | `create_escrow` | Create an escrow hold |
| `A2AReleaseEscrow` | `release_escrow` | Release an escrow hold |
| `A2ASearchServices` | `search_services` | Search the marketplace |
| `A2AGetTrustScore` | `get_trust_score` | Get server trust score |
| `A2ARegisterAgent` | `register_agent` | Register agent identity |
| `A2ASendMessage` | `send_message` | Send agent-to-agent message |

## Error Handling

SDK errors (`A2AError` and subclasses) are automatically wrapped as
`langchain_core.tools.ToolException`, so LangChain agents can handle them
gracefully:

```python
from langchain_core.tools import ToolException

try:
    result = await tool.arun({"agent_id": "a1"})
except ToolException as e:
    print(f"Tool failed: {e}")
```

Error types mapped: `AuthenticationError` (401), `RateLimitError` (429),
`InsufficientBalanceError` (402), `InsufficientTierError` (403),
`ToolNotFoundError` (404), `ServerError` (5xx).

## License

MIT
