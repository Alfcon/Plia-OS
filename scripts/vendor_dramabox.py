#!/usr/bin/env python3
"""
Download the ResembleAI/Dramabox HF Space and copy src/ and ltx2/ into
voice/dramabox/. Run once to vendor the inference code.

    python scripts/vendor_dramabox.py
"""
import shutil
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "ResembleAI/Dramabox"
EXCLUDE_FILES = {"train.py", "validate.py"}

ROOT = Path(__file__).parent.parent
DEST_BASE = ROOT / "voice" / "dramabox"


def _copy_tree(src: Path, dst: Path, exclude: set[str] = frozenset()) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in src.rglob("*"):
        if item.name in exclude:
            continue
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            count += 1
    return count


def main() -> None:
    print(f"Downloading {REPO_ID} snapshot...")
    snapshot = Path(
        snapshot_download(
            repo_id=REPO_ID,
            repo_type="space",
            token=None,
            ignore_patterns=["*.safetensors", "*.pt", "*.bin", "*.mp3", "*.wav"],
        )
    )
    print(f"Snapshot at: {snapshot}")

    for tree in ("src", "ltx2"):
        src = snapshot / tree
        dst = DEST_BASE / tree
        if not src.is_dir():
            print(f"  WARNING: {tree}/ not found in snapshot, skipping")
            continue
        n = _copy_tree(src, dst, exclude=EXCLUDE_FILES)
        init = dst / "__init__.py"
        if not init.exists():
            init.write_text("")
        print(f"  Copied {n} files → {dst}")

    print("Done. Commit voice/dramabox/src/ and voice/dramabox/ltx2/ to git.")


if __name__ == "__main__":
    main()
