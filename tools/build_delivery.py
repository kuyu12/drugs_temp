"""Package source and notebook without live snapshots or local caches."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
target = root / "dist/medical-devices-project.zip"
target.parent.mkdir(exist_ok=True)
files = [root / "pyproject.toml", root / "README.md", root / ".gitignore"]
for directory in ("src", "tests", "notebooks", "tools", "integration"):
    files.extend(p for p in (root / directory).rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".zip", ".pyc"})
files.extend((root / "dist").glob("*.whl"))
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
    for file in sorted(files):
        z.write(file, "medical-devices-registry/" + str(file.relative_to(root)))
print(target)
