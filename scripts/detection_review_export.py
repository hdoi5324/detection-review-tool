#!/usr/bin/env python3
"""Re-export COCO from a completed run directory's sibling store is not kept;
use the instances_reviewed.json already written, or re-run complete in the UI.

This helper validates / pretty-prints an exported COCO path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("coco_json", type=Path)
    args = p.parse_args()
    data = json.loads(args.coco_json.read_text())
    print(
        f"images={len(data.get('images', []))} "
        f"annotations={len(data.get('annotations', []))} "
        f"categories={len(data.get('categories', []))}"
    )


if __name__ == "__main__":
    main()
