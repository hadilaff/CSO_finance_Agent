"""Clear the Chroma index and re-embed every supported file in files/.

Run after changing the parser / chunker so stored chunks reflect the new logic.

Usage:
    python eval/reindex.py                 # all files in files/
    python eval/reindex.py file1.pdf ...   # only the named files
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag import clear_index, index_file, list_sources  # noqa: E402

FILES_DIR = ROOT / "files"
SUPPORTED = {".pdf", ".docx", ".pptx", ".txt", ".md"}


def main() -> None:
    if len(sys.argv) > 1:
        targets = [FILES_DIR / name for name in sys.argv[1:]]
    else:
        targets = sorted(p for p in FILES_DIR.iterdir() if p.suffix.lower() in SUPPORTED)

    if not targets:
        print(f"No files found in {FILES_DIR}")
        return

    print(f"Clearing existing Chroma index…")
    clear_index()

    print(f"Re-indexing {len(targets)} file(s):")
    for path in targets:
        if not path.exists():
            print(f"  ! missing: {path.name}")
            continue
        t0 = time.time()
        try:
            n_chunks = index_file(path.name, path.read_bytes())
        except Exception as e:
            print(f"  ! {path.name}: {e}")
            continue
        print(f"  {path.name}: {n_chunks} chunks ({time.time() - t0:.1f}s)")

    print(f"\nIndexed sources now in Chroma: {list_sources()}")


if __name__ == "__main__":
    main()
