"""Keep Hatch's implicit sdist additions inside the reviewed file inventory."""
from pathlib import Path
import tomllib

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class ReleaseInventoryHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        config = tomllib.loads((root / 'pyproject.toml').read_text())
        inventory = config['tool']['hatch']['build']['targets'][self.target_name]['only-include']
        for name in inventory:
            path = root / name
            if not path.is_file() or any((root / Path(*Path(name).parts[:i])).is_symlink() for i in range(1, len(Path(name).parts) + 1)):
                raise ValueError('Release inventory requires a regular source file: ' + name)
        # Hatch otherwise adds VCS ignore files (including parent files) and
        # build configuration outside only-include. Metadata/license/source
        # inputs are already listed; wheel metadata is generated independently.
        build_data['force_include'] = {}
