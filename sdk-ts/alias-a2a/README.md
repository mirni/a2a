# @a2a/sdk

> **Alias for [`@greenhelix/sdk`](https://www.npmjs.com/package/@greenhelix/sdk).**
> This package exists so that agents and developers searching for the
> `@a2a` scope find the canonical SDK.

## Install

```bash
npm install @a2a/sdk
# or
npm install @greenhelix/sdk    # canonical name (preferred for new code)
```

## Usage

```ts
import { A2AClient } from '@a2a/sdk';

const client = new A2AClient({
  baseUrl: 'https://api.greenhelix.net',
  apiKey: process.env.A2A_API_KEY,
});

const balance = await client.execute('get_balance', { agent_id: 'alice' });
```

All exports are re-exported verbatim from `@greenhelix/sdk`. See the
[main SDK README](https://github.com/mirni/a2a/tree/main/sdk-ts#readme)
for full documentation.

## License

MIT.
