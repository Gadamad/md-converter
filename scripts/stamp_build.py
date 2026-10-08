"""Record the exact source snapshot in a macOS bundle before signing."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import plistlib
import runpy
import subprocess
import sys


def main():
    project = Path(__file__).resolve().parents[1]
    app = Path(sys.argv[1])
    version = runpy.run_path(str(project / "src" / "app_version.py"))["VERSION"]
    revision = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=project, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=project, text=True).strip():
        revision += "-dirty"
    digest = hashlib.sha256()
    for path in sorted((project / "src").glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    info_path = app / "Contents" / "Info.plist"
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    info.update(CFBundleShortVersionString=version, CFBundleVersion=version,
                MDConverterRevision=revision, MDConverterSourceSHA256=digest.hexdigest(),
                MDConverterBuiltAt=datetime.now(timezone.utc).isoformat())
    with info_path.open("wb") as stream:
        plistlib.dump(info, stream)
    print(f"Build {version}, revision {revision}, source {digest.hexdigest()[:12]}")


if __name__ == "__main__":
    main()
