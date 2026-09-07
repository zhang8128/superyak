import re

_CODEX_RUN_KEY = re.compile(r"^codex:[0-9]+$")

def valid_codex_run_key(value: object) -> str | None:
    return value if isinstance(value, str) and _CODEX_RUN_KEY.fullmatch(value) else None
