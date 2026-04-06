#!/usr/bin/env python3
"""Deterministic test file sharding using greedy bin-packing.

Collects test counts per file via ``pytest --collect-only``, then assigns
files to shards so that each shard has roughly the same number of tests.

Usage:
    python scripts/ci/shard_tests.py <test-dir> <shard-id> <num-shards>

Outputs one test file path per line for the requested shard.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import defaultdict


def main() -> int:
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <test-dir> <shard-id> <num-shards>", file=sys.stderr)
        return 1

    test_dir = sys.argv[1].rstrip("/")
    shard_id = int(sys.argv[2])
    num_shards = int(sys.argv[3])

    if not 0 <= shard_id < num_shards:
        print(f"Error: shard-id must be 0..{num_shards - 1}", file=sys.stderr)
        return 1

    # Collect test IDs — run from the repo root so paths are absolute-ish
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_dir, "--collect-only", "-q", "--rootdir", "."],
        capture_output=True,
        text=True,
    )

    # Count tests per file.
    # pytest may report paths relative to rootdir — normalise to ensure
    # they include the test_dir prefix so callers can pass them back to pytest.
    file_counts: dict[str, int] = defaultdict(int)
    for line in result.stdout.splitlines():
        if "::" in line:
            raw_path = line.split("::")[0]
            # Ensure the path starts with the test_dir prefix
            if not raw_path.startswith(test_dir):
                # pytest reported a relative path like "tests/foo.py";
                # reconstruct the full relative path from test_dir's parent.
                parent = os.path.dirname(test_dir)  # e.g. "gateway"
                raw_path = os.path.join(parent, raw_path) if parent else raw_path
            file_counts[raw_path] += 1

    if not file_counts:
        print(f"Warning: no tests collected from {test_dir}", file=sys.stderr)
        return 0

    # Greedy bin-packing: sort by count descending, assign to lightest shard
    files_sorted = sorted(file_counts.items(), key=lambda x: -x[1])
    shard_loads = [0] * num_shards
    shard_files: list[list[str]] = [[] for _ in range(num_shards)]

    for path, count in files_sorted:
        lightest = min(range(num_shards), key=lambda i: shard_loads[i])
        shard_files[lightest].append(path)
        shard_loads[lightest] += count

    # Report shard distribution to stderr for CI visibility
    for i in range(num_shards):
        marker = " <--" if i == shard_id else ""
        print(
            f"  shard {i}: {len(shard_files[i])} files, {shard_loads[i]} tests{marker}",
            file=sys.stderr,
        )

    # Output file paths for requested shard
    for path in sorted(shard_files[shard_id]):
        print(path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
