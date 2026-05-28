#!/bin/bash
# Run the Waldo Spells test harness with all three tiers.
# Usage: ./run_harness.sh [--tiers fast,better,smart] [--corpus path] [extra args]

export CT2_MODEL_PATH=/home/michaelwicker/Documents/Waldo/WaldoSpells/models/gec-t5_small-ct2
export LLAMA_MODEL_PATH=/home/michaelwicker/Documents/Waldo/WaldoSpells/models/qwen2.5-3b-instruct-q4_k_m.gguf
export LLAMA_SERVER_BIN=/home/michaelwicker/Documents/Waldo/WaldoAI/models/llama-cpp/llama-server

[ -d "$CT2_MODEL_PATH" ]    || { echo "Missing CT2 model dir: $CT2_MODEL_PATH" >&2; exit 2; }
[ -f "$LLAMA_MODEL_PATH" ]  || { echo "Missing llama model: $LLAMA_MODEL_PATH" >&2; exit 2; }
[ -x "$LLAMA_SERVER_BIN" ]  || { echo "Missing llama-server binary: $LLAMA_SERVER_BIN" >&2; exit 2; }

source "$(dirname "$0")/venv/bin/activate"

python3 -m harness.report "$@"
