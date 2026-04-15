#!/bin/bash

#----------------------------------------------------------------------
# Build it
docker build -f Dockerfile.claude -t claude-code .

#----------------------------------------------------------------------
CLAUDE_BASE_DIR=~/.claude-dir
CLAUDE_DIR=$CLAUDE_BASE_DIR/$(basename $(pwd))
mkdir -p $CLAUDE_DIR
echo $CLAUDE_DIR

# Inside the docker container
CLAUDE_HOME=/home/claude

docker run -it --rm \
       --user $(id -u):$(id -g) \
       --dns-opt=single-request-reopen \
       -v "$(pwd)":/workdir \
       -e HOME=$CLAUDE_HOME \
       -v $CLAUDE_DIR:$CLAUDE_HOME \
       -e CLAUDE_CONFIG_DIR=$CLAUDE_HOME \
       -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
       claude-code



exit $?

       -v "$HOME/.claude.json":/tmp/.claude.json \
       -v "$HOME/.claude":/tmp/.claude \
       -e CLAUDE_CONFIG_DIR=/tmp/.claude \
