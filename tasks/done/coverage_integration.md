# Prompt

## Goal
Integrate coverage results in the github interface. Improve CI to gate merges on min test coverage (min 94% -- or whatever is now).

## Completed
- **Date:** 2026-04-03
- **Summary:** Added `--markdown` flag to `coverage_ratchet.py` that generates a Markdown table with module/baseline/current/delta/status columns. CI workflow now posts this as a PR comment using `gh pr comment --edit-last` (updates on subsequent pushes instead of spamming). Coverage ratchet gating was already in place.
