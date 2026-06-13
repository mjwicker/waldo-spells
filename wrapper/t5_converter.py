"""One-time conversion of T5 grammar-correction models from HuggingFace to CTranslate2 format.

Usage:
    # Convert default model (Unbabel/gec-t5_small) to INT8:
    python -m wrapper.t5_converter --output ./models/gec-t5_small-ct2

    # Convert a custom model to INT8:
    python -m wrapper.t5_converter --model vennify/t5-base-grammar-correction \
        --output ./models/gec-t5-base-ct2

    # Convert with different quantization (default: int8):
    python -m wrapper.t5_converter --model prithivida/grammar_error_correcter_v1 \
        --output ./models/gec-t5-prithivida-ct2 --quantization int8_float16

This shells out to ct2-transformers-converter (installed with ctranslate2).
Output directory is skipped if it already contains model.bin.

Requirements:
    pip install ctranslate2 transformers sentencepiece
"""

import argparse
import os
import subprocess
import sys


_MODEL_ID = "Unbabel/gec-t5_small"
_DEFAULT_OUTPUT = "./models/gec-t5_small-ct2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert gec-t5_small to CTranslate2 INT8 format")
    parser.add_argument("--output", default=_DEFAULT_OUTPUT, help="Output directory for CT2 model")
    parser.add_argument("--model", default=_MODEL_ID, help="HuggingFace model ID (default: Unbabel/gec-t5_small)")
    parser.add_argument("--quantization", default="int8", choices=["int8", "int8_float16", "float16", "float32"])
    args = parser.parse_args()

    # Check ctranslate2 is installed
    try:
        import ctranslate2  # noqa: F401
    except ImportError:
        print("ERROR: ctranslate2 not installed.", file=sys.stderr)
        print("Install: pip install ctranslate2 transformers sentencepiece", file=sys.stderr)
        return 1

    output_dir = os.path.abspath(args.output)
    model_bin = os.path.join(output_dir, "model.bin")

    if os.path.isfile(model_bin):
        print(f"Model already converted at {output_dir} — skipping.")
        print(f"Set: export CT2_MODEL_PATH={output_dir}")
        return 0

    print(f"Converting {args.model} → {output_dir} (quantization={args.quantization})")
    print("This will download ~240 MB from HuggingFace and produce ~120 MB output.")

    cmd = [
        "ct2-transformers-converter",
        "--model", args.model,
        "--output_dir", output_dir,
        "--quantization", args.quantization,
        "--force",
    ]

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("ERROR: conversion failed.", file=sys.stderr)
        return result.returncode

    print(f"\nDone. Set: export CT2_MODEL_PATH={output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
