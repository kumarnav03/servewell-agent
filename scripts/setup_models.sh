#!/usr/bin/env bash
# Pull the open-weight models used by the POC into the local Ollama runtime.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

LLM_MODEL="${LLM_MODEL:-qwen2.5:7b-instruct}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

if ! curl -sf http://localhost:11434/api/tags >/dev/null; then
  echo "Ollama is not running — starting 'ollama serve' in the background"
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 3
fi

ollama pull "$EMBED_MODEL"
ollama pull "$LLM_MODEL"
ollama list
