# a2a-crewai

CrewAI tool wrappers for the [A2A Commerce Platform](https://greenhelix.net) SDK.

## Installation

```bash
pip install a2a-crewai
```

## Quick Start

### Pre-built Tools

Use the 10 pre-built tool classes directly with any CrewAI Agent:

```python
from crewai import Agent, Crew, Task
from a2a_sdk import A2AClient
from a2a_crewai import A2AGetBalance, A2ADeposit, A2ASearchServices

client = A2AClient(base_url="https://api.greenhelix.net", api_key="a2a_...")

tools = [
    A2AGetBalance(client=client),
    A2ADeposit(client=client),
    A2ASearchServices(client=client),
]

agent = Agent(
    role="Finance Agent",
    goal="Manage agent wallets and payments",
    backstory="You handle all financial operations for the AI network.",
    tools=tools,
)

task = Task(
    description="Check the balance for agent-1",
    expected_output="The current balance",
    agent=agent,
)

crew = Crew(agents=[agent], tasks=[task])
result = crew.kickoff()
```

### Dynamic Toolkit

Load all tools (or a filtered subset) from the live catalog:

```python
from a2a_sdk import A2AClient
from a2a_crewai import A2AToolkit

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
from a2a_crewai import create_tool

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

SDK errors (`A2AError` and subclasses) are caught and returned as JSON
error objects, following CrewAI conventions:

```json
{"error": true, "message": "Rate limit exceeded", "code": "rate_limit", "status": 429}
```

This allows CrewAI agents to read and react to errors within their
reasoning loop.

## License

MIT
