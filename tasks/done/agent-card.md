# Prompt

## Registering agent card
Gives errors when submitting `https://api.greenhelix.net/.well-known/agent.json` on https://a2aregistry.org/submit

```
Invalid agent card format: 24 validation errors for AgentCreate skills.0.examples Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.0.inputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.0.outputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.1.examples Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.1.inputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.1.outputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.2.examples Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.2.inputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.2.outputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.3.examples Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.3.inputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.3.outputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.4.examples Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.4.inputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.4.outputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.5.examples Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.5.inputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.5.outputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.6.examples Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.6.inputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.6.outputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.7.examples Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.7.inputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type skills.7.outputModes Input should be a valid list [type=list_type, input_value=None, input_type=NoneType] For further information visit https://errors.pydantic.dev/2.12/v/list_type

```

## Goal
Address the errors so that we can register agent card.

## Completed

**Date:** 2026-04-13

**Root cause:** The agent card's skill objects were missing `examples`,
`inputModes`, and `outputModes` fields. a2aregistry.org's Pydantic model
requires these as `list` (not `None`/missing).

**Fix:** Added `"examples": []`, `"inputModes": ["application/json"]`,
`"outputModes": ["application/json"]` to each skill in
`gateway/src/routes/agent_card.py`.

**Test:** `test_agent_card_skills_have_a2a_registry_fields` in
`gateway/tests/test_health.py`.

After deploying, re-submit `https://api.greenhelix.net/.well-known/agent.json`
to https://a2aregistry.org/submit.
