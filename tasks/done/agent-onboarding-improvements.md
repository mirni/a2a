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

## Completed
- **Date**: 2026-04-07
- **PR**: #74 (pending)
- **Summary**:
  - Added identity registration (Phase 1) to `examples/demo_autonomous_agent.py`
  - Updated Python SDK README quickstart with `register_agent` example
  - Updated TypeScript SDK README quickstart with `registerAgent` example
  - Tier review: all marketplace reads already FREE. `register_service` is PRO — downgrade to starter left for human decision.
  - Monitoring items remain open (require live deployment observation)
