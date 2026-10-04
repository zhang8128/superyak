"""aDNA coordination memos for the wormhole bridge: names, front matter, parsing and the persona map.
Pure functions; the bridge never runs a model and never fetches anything while relaying."""
import datetime
import json
from pathlib import Path
import re
import urllib.request
from .station import label, read_json

STATION_VAULT = 'Station.aDNA'
REGISTRY = 'https://adna.network/api/registry.v1.json'
EXPIRES_DAYS = 14
MENTION = re.compile(r'(?<![\w@])@([a-z0-9][a-z0-9_.-]{1,63})', re.IGNORECASE)
LINE = re.compile(r'^([A-Za-z_][\w-]*):[ \t]*(.*)$')
DOUBLE_QUOTED = re.compile(r'^"(?:[^"\\]|\\.)*"')
SINGLE_QUOTED = re.compile(r"^'(?:[^']|'')*'")
COMMENT = re.compile(r'(?:^|\s)#.*$')
TOKEN_MAX, SLUG_MAX = 24, 60  # keep a memo's file name far below the 255-byte file system limit


def mentioned(body):
    """Lowercase @names in a message, in order, without trailing punctuation."""
    return list(dict.fromkeys(m.group(1).rstrip('._-').lower() for m in MENTION.finditer(body or '')))


def slug(text, words=6):
    """Up to `words` lowercase [a-z0-9] tokens joined by '_': each token at most 24 characters, the
    whole slug at most 60."""
    tokens = [t[:TOKEN_MAX] for t in re.findall(r'[a-z0-9]+', re.sub(r'@\S+', ' ', (text or '').lower()))]
    return '_'.join(tokens[:words])[:SLUG_MAX].rstrip('_') or 'message'


def memo_name(day, persona, text, taken):
    first = next((line for line in (text or '').splitlines() if line.strip()), '')
    base = f'coord_{day:%Y_%m_%d}_station_to_{slug(persona, 1)}_{slug(first)}'
    name, n = f'{base}.md', 2
    while name in taken:
        name, n = f'{base}_{n}.md', n + 1
    return name


def _yaml_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return '[' + ', '.join(str(v) for v in value) + ']'
    return json.dumps(str(value), ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar


def front_matter(fields):
    return '---\n' + ''.join(f'{key}: {_yaml_value(value)}\n' for key, value in fields.items()) + '---\n'


def outbound_memo(*, day, persona, vault, author, room_title, room_id, message_id, text, taken):
    """(file name, markdown) for one station message addressed to one lattice persona. `text` is
    already secret-redacted by the caller."""
    name = memo_name(day, persona, text, taken)
    who, subject = label(author), label(text, 80)
    fields = {
        'type': 'coordination', 'coordination_class': 'outbound_memo',
        'from': f'{STATION_VAULT} ({who} via Wormhole)', 'to': f'{vault} ({persona})',
        'from_vault': STATION_VAULT, 'from_persona': who, 'to_vault': vault, 'to_persona': persona,
        'subject': subject, 'date': f'{day:%Y-%m-%d}',
        'expires': f'{day + datetime.timedelta(days=EXPIRES_DAYS):%Y-%m-%d}',
        'status': 'staged', 'urgency': 'info', 'reply_required': True,
        'station_room': room_id, 'station_message': message_id, 'tags': ['coordination', 'station', 'wormhole'],
    }
    quoted = '\n'.join('> ' + line if line.strip() else '>' for line in text.splitlines()) or '>'
    body = (f'# {subject}\n\n'
            f'{who} wrote this in the station room "{label(room_title)}" on Deep Space 9, the Superyak station on '
            f"Andy's Raspberry Pi, and addressed it to {persona} through the wormhole bridge.\n\n"
            f'{quoted}\n\n'
            f'Reply by adding a new memo to `{STATION_VAULT}/who/coordination/inbox/` with '
            f'`to: "{STATION_VAULT} (Wormhole)"` and `in_reply_to: {name}`. To show it was picked up, add an empty '
            f'file `{STATION_VAULT}/who/coordination/receipts/{name}`.\n')
    return name, front_matter(fields) + '\n' + body


def _scalar(raw):
    if raw.startswith('"'):
        match = DOUBLE_QUOTED.match(raw)  # the string alone: whatever follows the closing quote is a comment
        if not match:
            return raw.strip('"')
        try:
            return json.loads(match.group(0))
        except ValueError:
            return match.group(0)[1:-1]
    if raw.startswith("'"):
        match = SINGLE_QUOTED.match(raw)
        return match.group(0)[1:-1].replace("''", "'") if match else raw.strip("'")
    raw = COMMENT.sub('', raw).strip()  # an unquoted ` #` starts a comment, before booleans and lists are told apart
    if raw.startswith('[') and raw.endswith(']'):
        return [item.strip().strip('"\'') for item in raw[1:-1].split(',') if item.strip()]
    if raw.lower() in ('true', 'false'):
        return raw.lower() == 'true'
    if raw in ('|', '>', '|-', '>-', '|+', '>+'):
        return ''
    return raw


def parse_memo(text):
    """(front matter, body). A tolerant subset of YAML: top-level `key: value` lines only; quoted
    strings unquoted; `[a, b]` lists split; block scalars become ''; nested maps are ignored. A leading byte order
    mark is dropped."""
    text = text.removeprefix('\ufeff')
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}, text
    fields = {}
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            return fields, '\n'.join(lines[index + 1:]).strip()
        match = LINE.match(line)
        if match:
            fields[match.group(1)] = _scalar(match.group(2).strip())
    return {}, text


def addressed_to_station(fields):
    return any(STATION_VAULT.lower() in str(fields.get(key, '')).lower() for key in ('to', 'to_vault'))


def sender(fields):
    """(persona, vault) of an inbound memo, from from_persona/from_vault or `from: "Vault (Persona)"`."""
    persona, vault = str(fields.get('from_persona') or ''), str(fields.get('from_vault') or '')
    match = re.match(r'^\s*([^()]+?)\s*\(([^()]+)\)', str(fields.get('from') or ''))
    if match:
        vault, persona = vault or match.group(1), persona or match.group(2)
    return label(persona or 'someone'), label(vault or 'the lattice')


def _safe(text, limit=80):
    """label() of text whose '@' is already spelled '(at)', so the limit bounds what is really posted."""
    return label(str(text).replace('@', '(at)'), limit)


def inbound_post(fields, body, name, limit=4000):
    """A station post for a memo addressed to the station: labelled header, quoted body, no '@'.
    The quoted body (with its '> ' markers) is cut at `limit` characters after '@' is spelled out."""
    persona, vault = (_safe(part) for part in sender(fields))
    status = str(fields.get('status') or '').lower()
    notes = []
    if fields.get('ratification_required') is True or status == 'awaiting_ratification':
        notes.append('awaiting ratification')
    if status == 'ratified' and fields.get('in_reply_to'):  # ratification answers an earlier memo
        notes.append(f'ratified by {_safe(fields.get("ratified_by") or persona)}')
    head = f'**{persona} ({vault}) via the wormhole:** {_safe(fields.get("subject") or "", 200)}'
    if notes:
        head += f' ({"; ".join(notes)})'
    quoted = '\n'.join('> ' + line if line.strip() else '>' for line in body.replace('@', '(at)').splitlines()) or '>'
    if len(quoted) > limit:
        quoted = quoted[:limit].rstrip() + ' …'
    return f'{head}\n\n{quoted}\n\n`{_safe(name)}`'.replace('@', '(at)')


def personas_from_registry(registry):
    """{persona lowercase: {'persona': display name, 'vault': vault}}; rows without a persona are
    skipped, and the first vault to claim a persona keeps it."""
    out = {}
    for row in registry.get('vaults', []):
        persona, vault = row.get('persona'), row.get('vault')
        if isinstance(persona, str) and persona.strip() and isinstance(vault, str) and vault.strip():
            out.setdefault(persona.strip().lower(), {'persona': persona.strip(), 'vault': vault.strip()})
    return out


def fetch_registry(url=REGISTRY, opener=urllib.request.urlopen):
    with opener(url, timeout=30) as response:
        return json.loads(response.read())


def load_personas(path):
    """The registry map plus personas.local.json beside it (local entries win). Keys are lowercase,
    and 'wormhole' is reserved for the bridge itself."""
    path = Path(path)
    personas = {k.lower(): v for k, v in (read_json(path, {}) or {}).items()}
    personas.update({k.lower(): v for k, v in (read_json(path.with_name('personas.local.json'), {}) or {}).items()})
    personas.pop('wormhole', None)
    return personas
