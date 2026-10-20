"""Package source and notebook without live snapshots or local caches."""
from pathlib import Path
import subprocess
import tomllib
import zipfile

root = Path(__file__).resolve().parents[1]
required = ["src/moh_medical_devices/__init__.py", "src/moh_medical_devices/client.py",
            "src/moh_medical_devices/pandas_ingestion.py",
            "src/moh_medical_devices/record_normalization.py",
            "notebooks/medical_devices_ingestion.ipynb"]
for filename in required:
    if not (root / filename).is_file():
        raise SystemExit(f"Required delivery file is missing: {filename}")
if (root / ".git").exists():
    # A notebook must not be committed while its implementation stays untracked.
    subprocess.run(["git", "ls-files", "--error-unmatch", "--", *required],
                   cwd=root, check=True, stdout=subprocess.DEVNULL)
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
target = root / "dist/medical-devices-project.zip"
target.parent.mkdir(exist_ok=True)
files = [root / "pyproject.toml", root / "README.md", root / ".gitignore"]
for directory in ("src", "tests", "notebooks", "tools", "integration"):
    files.extend(p for p in (root / directory).rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts
                 and not any(part.endswith(".egg-info") for part in p.parts)
                 and p.name != ".DS_Store" and p.suffix not in {".zip", ".pyc"})
files.extend((root / "dist").glob(f"moh_medical_devices_pipeline-{version}-*.whl"))
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
    for file in sorted(files):
        z.write(file, "medical-devices-registry/" + str(file.relative_to(root)))
print(target)
