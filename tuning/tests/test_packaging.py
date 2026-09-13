import shutil
import subprocess
import tarfile
import uuid
import zipfile
from pathlib import Path

import tomllib


def test_release_inventory_excludes_unlisted_private_state(tmp_path):
    sentinel = uuid.uuid4().hex.encode()
    root = Path(__file__).parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    inventory = config["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]
    source = tmp_path / "source"
    for name in inventory:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    for name in [
        ".engram/patient.json",
        "superyak_tuning/private_record.json",
        "examples/private.json",
        ".gitignore",
    ]:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sentinel)
    output = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--project", str(source), "--out-dir", str(output)],
        check=True,
        capture_output=True,
    )
    with tarfile.open(next(output.glob("*.tar.gz"))) as archive:
        names = {"/".join(n.split("/")[1:]) for n in archive.getnames()}
        assert names == set(inventory) | {"PKG-INFO"}
        for member in archive.getmembers():
            if member.isfile():
                assert sentinel not in archive.extractfile(member).read()
    with zipfile.ZipFile(next(output.glob("*.whl"))) as archive:
        code = {n for n in archive.namelist() if ".dist-info/" not in n}
        assert code == set(
            config["tool"]["hatch"]["build"]["targets"]["wheel"]["only-include"]
        )
        assert all(sentinel not in archive.read(n) for n in archive.namelist())
