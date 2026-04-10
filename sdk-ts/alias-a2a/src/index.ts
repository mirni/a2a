/**
 * @a2a/sdk — alias package for @greenhelix/sdk.
 *
 * Exists so that agents and tooling searching npm for the "@a2a" scope
 * discover and install the canonical Green Helix SDK without surprise.
 * Every symbol is re-exported verbatim from @greenhelix/sdk.
 *
 * Prefer importing from @greenhelix/sdk directly in new code.
 */

export * from '@greenhelix/sdk';
