#!/bin/bash
# Run the Waldo Spells test harness.
# Usage: ./run_harness.sh [--full] [--tiers fast,better,smart] [--corpus path] [extra args]
#   --full  run all four tiers (fast,better,smart,edge) using sources.yaml (default is fast,better,smart)

export CT2_MODEL_PATH=/home/michaelwicker/Documents/Waldo/WaldoSpells/models/gec-t5-base-ct2
export CT2_TOKENIZER_ID=t5-base
export LLAMA_MODEL_PATH=/home/michaelwicker/Documents/Waldo/WaldoAI/models/phi-4-mini-q4/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf
export LLAMA_SERVER_BIN=/home/michaelwicker/Documents/Waldo/WaldoAI/models/llama-cpp/llama-server

[ -d "$CT2_MODEL_PATH" ]    || { echo "Missing CT2 model dir: $CT2_MODEL_PATH" >&2; exit 2; }
[ -f "$LLAMA_MODEL_PATH" ]  || { echo "Missing llama model: $LLAMA_MODEL_PATH" >&2; exit 2; }
[ -x "$LLAMA_SERVER_BIN" ]  || { echo "Missing llama-server binary: $LLAMA_SERVER_BIN" >&2; exit 2; }

source "$(dirname "$0")/venv/bin/activate"

# --full: expand to all four tiers before passing remaining args to report.py
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--full" ]; then
        ARGS+=(--tiers fast,better,smart,edge)
    else
        ARGS+=("$arg")
    fi
done

python3 -m harness.report "${ARGS[@]}"
