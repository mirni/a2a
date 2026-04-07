# Agent Onboarding Improvements

Follow-up items from felix-e3edd460 session analysis (PR #69 report).

## SDK Examples
- SDK examples (`examples/`) should show identity registration as part of onboarding flow
- TypeScript SDK (`sdk-ts/`) quickstart should include identity step

## Tier Access Review
- Consider making `register_service` available on starter tier (currently pro-only)
- Evaluate whether marketplace read operations should be available to starter tier

## Monitoring
- Monitor felix-e3edd460 on next run to verify auto-registration resolves the identity gap
- Track whether `next_steps` hints in error responses reduce API fumbling
- Review analytics after cost_per_call=0.001 change to confirm credit consumption visibility
