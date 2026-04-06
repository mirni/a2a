# Prompt

## Goal
Optimize CI pipeline runtime.

## Details
Currently the `test` job in the CI pipeline is the longest-running and takes ~7min to run. This runtime has been growing.

## Instructions
* Plan refactoring to split the `test` job into two or three separate test jobs that run in parallel.
* Add back test jobs utilizing different python version, so that compatibility with both 3.12 and 3.13 is tested in each CI pipeline. The gh pipeline minutes are not an issue any more, since the repo is public now.

## Completed
- **Date**: 2026-04-06
- **Summary**: Split single `test` job into `test-gateway` and `test-products`, each with a matrix for Python 3.12 and 3.13 (4 parallel jobs total). Coverage uploads only from 3.12 runs. Applied to both ci.yml and release.yml.
