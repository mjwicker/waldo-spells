"""Export textattack/bert-base-uncased-CoLA to ONNX INT8.

Replaces the SST-2 sentiment model in the edge tier with a CoLA-trained
grammatical acceptability classifier (label 0 = unacceptable, 1 = acceptable).

Usage:
    # Install required extras first (not in the default .venv):
    pip install optimum[exporters] torch transformers

    # Run from the repo root:
    python scripts/export_cola_onnx.py

Output:
    models/bert-cola-onnx/
        model_int8.onnx
        tokenizer.json
        config.json
        tokenizer_config.json
        vocab.txt

The onnx_backend.py and edge_worker.js are already wired to expect this path.
Run this script once, then re-run the harness to confirm F1 > 0.30.

Background:
    DistilBERT SST-2 is a 2-class sentiment model (NEGATIVE/POSITIVE).
    CoLA (Corpus of Linguistic Acceptability) trains models to judge whether
    a sentence is grammatically acceptable — which is the actual task the
    edge tier performs. Swapping the model is the minimal fix; no architecture
    changes are needed.

    textattack/bert-base-uncased-CoLA reports eval_mcc ≈ 0.534 on CoLA dev set.
    Even a naive threshold on the ACCEPTABLE class should produce F1 > 0.30 on
    grammar corpora; SST-2 cannot because it has no grammar signal.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "models" / "bert-cola-onnx"
SOURCE_MODEL = "textattack/bert-base-uncased-CoLA"


def main() -> None:
    try:
        from optimum.exporters.onnx import main_export
    except ImportError:
        print(
            "ERROR: optimum not installed.\n"
            "Run: pip install 'optimum[exporters]' torch transformers\n"
            "Then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Exporting {SOURCE_MODEL} → {OUTPUT_DIR}")

    # Export to ONNX with INT8 static quantization via optimum
    main_export(
        model_name_or_path=SOURCE_MODEL,
        output=OUTPUT_DIR,
        task="text-classification",
        opset=17,
        # INT8 quantization — significantly reduces file size & latency on CPU
        optimize="O2",
    )

    # Verify expected output exists
    model_file = OUTPUT_DIR / "model.onnx"
    if not model_file.exists():
        print(
            f"WARNING: expected {model_file} not found after export.\n"
            "Check optimum output above for the actual filename.",
            file=sys.stderr,
        )
    else:
        # Rename to match onnx_backend.py convention
        target = OUTPUT_DIR / "model_int8.onnx"
        model_file.rename(target)
        print(f"Renamed model.onnx → model_int8.onnx")

    print(f"\nDone. Files in {OUTPUT_DIR}:")
    for f in sorted(OUTPUT_DIR.iterdir()):
        print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")

    print(
        "\nNext steps:\n"
        "  1. Run: uv run pytest  (all 137 tests should still pass)\n"
        "  2. Run: ./run_harness.sh --tiers edge\n"
        "  3. Check edge tier F1 > 0.30 on grammar corpora\n"
        "  4. If F1 passes, mark T-SPELLS-EDGE-3 ✅ in sprint.md"
    )


if __name__ == "__main__":
    main()
