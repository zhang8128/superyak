"""Run a script under an audit hook that reports on stderr, as `AUDIT ...` lines, everything that writes or reaches a
database: a file opened for writing, a write-like os, shutil or tempfile call, a writable mmap, sqlite3 imported or
connected, or a database file opened at all. Used as `python -B lessons_audit.py <script> <args...>`. It writes
nothing itself: the lines go to the stderr it was given. When the script ends it also says which of its modules was
imported (`AUDIT imported <name>`), so a test can pin a light import path.

NOWRITE_PROMPT_LIMIT, when set, replaces the lessons hook's 150 ms, so a loaded test machine can't make the hook
silent and the test pass for the wrong reason."""
import os
import runpy
import sys

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
WRITE_EVENTS = {
    'os.mkdir', 'os.rename', 'os.remove', 'os.rmdir', 'os.symlink', 'os.link', 'os.truncate', 'os.chmod', 'os.chown',
    'os.lchmod', 'os.lchown', 'os.chflags', 'os.lchflags', 'os.utime', 'os.mkfifo', 'os.mknod', 'shutil.copyfile',
    'shutil.copymode', 'shutil.copystat', 'shutil.copytree', 'shutil.move', 'shutil.rmtree', 'tempfile.mkstemp',
    'tempfile.mkdtemp', 'sqlite3.connect', 'sqlite3.connect/handle',
}
DATABASES = ('.sqlite3', '.sqlite', '.db', '.db-wal', '.sqlite3-wal')
WATCHED = ('superyak_agent.station', 'superyak_agent.__main__', 'sqlite3')


def report(*what):
    os.write(2, ('AUDIT ' + ' '.join(repr(w) for w in what) + '\n').encode())


def audit(event, args):
    if event == 'open':
        path, mode, flags = (tuple(args) + (None, None, None))[:3]
        if isinstance(path, int):
            return  # a descriptor already open (subprocess wraps its pipes so): the open that made it was audited
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & WRITE_FLAGS):
            report('write', path)
        elif isinstance(path, (str, bytes)) and os.fsdecode(path).endswith(DATABASES):
            report('database', path)
    elif event in WRITE_EVENTS:
        report(event, args[:1])
    elif event == 'mmap.__new__' and len(args) > 2 and args[2] != 1:  # 1 is mmap.ACCESS_READ
        report('writable mmap', args)
    elif event == 'import' and args and args[0] == 'sqlite3':
        report('import', 'sqlite3')


script, sys.argv = sys.argv[1], sys.argv[1:]
sys.addaudithook(audit)
if os.environ.get('NOWRITE_PROMPT_LIMIT'):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0] = [here, os.path.join(os.path.dirname(here), 'team')]
    import superyak_agent.lessons_hook as lessons_hook  # the same module object run_agent.py then imports
    lessons_hook.LIMITS['UserPromptSubmit'] = float(os.environ['NOWRITE_PROMPT_LIMIT'])
try:
    runpy.run_path(script, run_name='__main__')
finally:
    for name in WATCHED:
        if name in sys.modules:
            report('imported', name)
