"""One frozen research task, independent of the continuing Atlas worker."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for name, module in tuple(sys.modules.items()):
    if name == 'workbench' or name.startswith('workbench.'):
        location = getattr(module, '__file__', None)
        if not location or not Path(location).resolve().is_relative_to(ROOT / 'atlas'):
            raise RuntimeError('Another Atlas snapshot is imported; use a separate process')
sys.path[:0] = [str(ROOT / 'atlas'), str(ROOT / 'engram')]
