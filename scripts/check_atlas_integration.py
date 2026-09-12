"""Check the bundled public pilot against both Atlas and Lighthouse validators."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="superyak-atlas-integration-") as temporary:
        demo = subprocess.run(
            [sys.executable, "-S", str(ROOT / "scripts/atlas.py"),
             "--project", str(Path(temporary) / "project")],
            cwd=temporary, check=True, capture_output=True, text=True, timeout=30,
        )
        report = json.loads(demo.stdout)
        publications = list(report["publications"].values())
        if report["publication_status"] != "current" or len(publications) != 2:
            raise RuntimeError("The public pilot did not produce both current publications")
        subprocess.run(
            [sys.executable, "-S", str(ROOT / "atlas/scripts/check_lighthouse_interop.py"),
             "--lighthouse", str(ROOT / "lighthouse"), *publications],
            cwd=temporary, check=True, timeout=45,
        )


if __name__ == "__main__":
    main()
