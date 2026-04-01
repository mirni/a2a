#!/bin/bash

# Build it
docker build -f Dockerfile.claude -t claude-code .

docker run -it --rm \
       --user $(id -u):$(id -g) \
       --dns-opt=single-request-reopen \
       -v "$(pwd)":/workdir \
       -v "$HOME/.claude.json":/tmp/.claude.json \
       -v "$HOME/.claude":/tmp/.claude \
       -e CLAUDE_CONFIG_DIR=/tmp/.claude \
       -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
       claude-code
