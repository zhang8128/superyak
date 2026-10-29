"""A stand-in for Rio Grande's `lessons query` (first rail spec section 5), run as `<python> lessons_stub.py --data-dir
<dir>`. It reads the request on stdin and answers from fixtures in <dir>:

- `answer-<kind>.json`, else `answer.json`: the answer's lessons, where kind is prompt, command (words_only), failure
  (an error or a command) or start. It honours the request's `limit` and skips the ids in `seen`, as the query does,
  unless `ignore-limit` or `ignore-seen` is present: then the hook's own cut and skip are what's left.
- `raw`: bytes printed as they are, in place of an answer; `exit`: the exit code; `sleep`: seconds to wait first.
- `record`: when present, each request is appended to `sent.jsonl`. Without it the stub writes nothing, for the test
  that the hook writes nothing at a prompt.
- `receipt`: after the sleep, `receipt` is appended to `late.txt`, as the query's commit writes receipts after its work;
  `grandchild`: first a process of its own session is started that appends `grandchild` to `late.txt` 1.5 s later."""
import json
import subprocess
import sys
import time
from pathlib import Path

data = Path(sys.argv[sys.argv.index('--data-dir') + 1])
request = json.loads(sys.stdin.read())
if (data / 'record').exists():
    with open(data / 'sent.jsonl', 'a') as stream:
        stream.write(json.dumps(request) + '\n')
if (data / 'grandchild').exists():
    subprocess.Popen([sys.executable, '-S', '-c', 'import sys, time; time.sleep(1.5); open(sys.argv[1], "a").write('
                      '"grandchild\\n")', str(data / 'late.txt')], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if (data / 'sleep').exists():
    time.sleep(float((data / 'sleep').read_text()))
if (data / 'receipt').exists():
    with open(data / 'late.txt', 'a') as stream:
        stream.write('receipt\n')
if (data / 'exit').exists():
    sys.exit(int((data / 'exit').read_text()))
if (data / 'raw').exists():
    sys.stdout.buffer.write((data / 'raw').read_bytes())
    sys.exit(0)
kind = ('prompt' if 'prompt' in request else 'command' if request.get('words_only') else
        'failure' if 'error' in request or 'command' in request else 'start')
fixture = data / f'answer-{kind}.json'
lessons = json.loads((fixture if fixture.exists() else data / 'answer.json').read_text()) if \
    (fixture.exists() or (data / 'answer.json').exists()) else []
seen = set() if (data / 'ignore-seen').exists() else set(request.get('seen') or [])
limit = None if (data / 'ignore-limit').exists() else request['limit']  # a request without `limit` fails here
print(json.dumps({'lessons': [l for l in lessons if l['id'] not in seen][:limit]}))
