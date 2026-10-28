"""The lessons provider's seam (Ruling 31). Tardis's branch replaces this module with the rail's provider, against the
same signature; until then it holds nothing. The hold entry uses only `candidates`.

A provider gets the command, the session record's dict, the time and `limit`, the most lessons this deny may carry (1
to 3; it isn't asked when no hold is left). It keeps its own entries under `record['lessons']`, marks them for each
Hold it returns, and never saves: the entry saves once, when it prints or when an unheld command spends a checklist's
pass (section 2's M1), and the record it saves then holds what a provider left in it. Each Hold's text is at most
holds.LESSON_BYTES bytes, and the entry never cuts one. With no checklist in the deny (`limit` 3), the first Hold's
text starts "Held once: lesson <id> from <ship> applies." (Ruling 35).
"""
from superyak_agent.holds import Hold


def candidates(command: str, record: dict, now: float, limit: int) -> list[Hold]:
    return []
