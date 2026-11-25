"""Create a clean release ZIP containing the app source and all 50 PDFs."""
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "outputs" / "Finwell_Full_Product.zip"
EXCLUDED_DIRS = {".git", ".next", "node_modules", "outputs", "work", ".vercel", "__pycache__", ".venv", "venv", "data"}
EXCLUDED_FILES = {".env", ".DS_Store"}
DEST.parent.mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(DEST, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as archive:
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.resolve() == DEST:
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.name in EXCLUDED_FILES or path.suffix.lower() in {".pyc", ".sqlite3", ".db"}:
            continue
        archive.write(path, Path("finwell") / relative)

print(f"Created release archive: {DEST} ({DEST.stat().st_size:,} bytes)")
