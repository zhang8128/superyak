"""Code index identity and replacement regressions against real SQLite storage."""

from contextlib import closing
import json
import sqlite3
import textwrap

import pytest

from indexer import index_file
from storage import Storage


VECTOR = [1.0] + [0.0] * 767


class FakeEmbeddings:
    def embed(self, texts):
        return [VECTOR[:] for _ in texts]


def _index(tmp_db, tmp_path, source, filename="sample.py", language="python"):
    path = tmp_path / filename
    path.write_text(textwrap.dedent(source))
    index_file(tmp_db, FakeEmbeddings(), path, language, tmp_path)
    return path


def _assert_searchable(store, expected_ids, term):
    assert set(store.search_fts(term)) == expected_ids
    assert {eid for eid, _ in store.search_vectors("entity", VECTOR, k=100)} == {
        row[0] for row in store.conn.execute("SELECT id FROM entities")
    }


@pytest.mark.parametrize(
    ("filename", "language", "source"),
    [
        ("sample.py", "python", """\
            class First:
                def run(self): pass
            class Second:
                def run(self): pass
            def outer():
                def run(): pass
            def flat(): pass
        """),
        ("sample.js", "javascript", """\
            class First { run() {} }
            class Second { run() {} }
            function outer() { function run() {} }
            function flat() {}
        """),
        ("sample.ts", "typescript", """\
            class First { run(): void {} }
            class Second { run(): void {} }
            function outer(): void { function run(): void {} }
            function flat(): void {}
        """),
    ],
)
def test_same_named_symbols_in_different_scopes_survive_reindex(
    tmp_db, tmp_path, filename, language, source
):
    path = _index(tmp_db, tmp_path, source, filename, language)
    index_file(tmp_db, FakeEmbeddings(), path, language, tmp_path)

    with closing(Storage.open_read_only(tmp_db.db_path)) as persisted:
        runs = {f"symbol:{filename}::{name}.run" for name in ("First", "Second", "outer")}
        _assert_searchable(persisted, runs, "run")
        assert persisted.get_entity(f"symbol:{filename}::flat") is not None
        assert persisted.conn.execute("SELECT count(*) FROM entities").fetchone()[0] == 7
        for eid in runs:
            metadata = json.loads(persisted.get_entity(eid)["metadata"])
            assert metadata["qualified_name"] == eid.split("::")[1]


@pytest.mark.parametrize("language,extension", [("javascript", "js"), ("typescript", "ts")])
def test_bound_arrow_and_object_scopes_keep_local_symbols_distinct(
    tmp_db, tmp_path, language, extension
):
    filename = f"sample.{extension}"
    _index(tmp_db, tmp_path, """\
        const first = () => { function run() {} };
        const second = () => { function run() {} };
        const left = { run() {} };
        const right = { run() {} };
    """, filename, language)

    with closing(Storage.open_read_only(tmp_db.db_path)) as persisted:
        _assert_searchable(persisted, {
            f"symbol:{filename}::{scope}.run" for scope in ("first", "second", "left", "right")
        }, "run")


def test_nested_classes_and_namespaces_keep_the_full_scope(tmp_db, tmp_path):
    _index(tmp_db, tmp_path, """\
        class First:
            class Inner:
                def run(self): pass
        class Second:
            class Inner:
                def run(self): pass
    """)
    _index(tmp_db, tmp_path, """\
        namespace First { export class Inner { run() {} } }
        namespace Second { export class Inner { run() {} } }
    """, "namespaces.ts", "typescript")

    with closing(Storage.open_read_only(tmp_db.db_path)) as persisted:
        _assert_searchable(persisted, {
            "symbol:sample.py::First.Inner.run", "symbol:sample.py::Second.Inner.run",
            "symbol:namespaces.ts::First.Inner.run", "symbol:namespaces.ts::Second.Inner.run",
        }, "run")


@pytest.mark.parametrize(
    ("filename", "language", "source", "expected_count"),
    [
        ("sample.py", "python", """\
            from typing import overload
            @overload
            def run(value: str) -> str: ...
            @overload
            def run(value: int) -> int: ...
            def run(value): return value
        """, 3),
        ("sample.js", "javascript", "const obj = { get run() {}, set run(value) {} };", 2),
        ("sample.ts", "typescript", """\
            function run(value: string): string;
            function run(value: number): number;
            function run(value: any): any { return value; }
        """, 3),
        ("sample.ts", "typescript", """\
            class Worker {
                run(value: string): string;
                run(value: number): number;
                run(value: any): any { return value; }
            }
        """, 3),
    ],
)
def test_repeated_declarations_have_distinct_repeatable_ids(
    tmp_db, tmp_path, filename, language, source, expected_count
):
    path = _index(tmp_db, tmp_path, source, filename, language)
    original = set(tmp_db.search_fts("run"))
    assert len(original) == expected_count
    index_file(tmp_db, FakeEmbeddings(), path, language, tmp_path)
    with closing(Storage.open_read_only(tmp_db.db_path)) as persisted:
        _assert_searchable(persisted, original, "run")


@pytest.mark.parametrize("failure", ["read", "embed", "lazy_embed", "short_embed", "vector", "insert"])
def test_failed_replacement_preserves_persisted_symbols_and_search(
    tmp_db, tmp_path, failure
):
    path = _index(tmp_db, tmp_path, "def old_first(): pass\ndef old_second(): pass\n")
    before = [dict(row) for row in tmp_db.conn.execute("SELECT * FROM entities ORDER BY id")]
    path.write_text("def newalpha(): pass\ndef newbeta(): pass\n")

    class FailingEmbeddings:
        def embed(self, texts):
            if failure == "embed":
                raise RuntimeError("embedding unavailable")
            if failure == "lazy_embed":
                def vectors():
                    yield VECTOR[:]
                    raise RuntimeError("embedding stream interrupted")
                return vectors()
            if failure == "short_embed":
                return [VECTOR[:]]
            if failure == "vector":
                return [VECTOR[:], [1.0]]
            return [VECTOR[:] for _ in texts]

    if failure == "read":
        path.unlink()
        error = FileNotFoundError
    elif failure == "short_embed":
        error = ValueError
    elif failure in ("vector", "insert"):
        error = sqlite3.DatabaseError
    else:
        error = RuntimeError
    if failure == "insert":
        tmp_db.conn.execute("""
            CREATE TRIGGER reject_second BEFORE INSERT ON entities
            WHEN NEW.name = 'newbeta'
            BEGIN SELECT RAISE(ABORT, 'replacement insert rejected'); END
        """)

    with pytest.raises(error):
        index_file(tmp_db, FailingEmbeddings(), path, "python", tmp_path)

    with closing(Storage.open_read_only(tmp_db.db_path)) as persisted:
        assert [dict(row) for row in persisted.conn.execute("SELECT * FROM entities ORDER BY id")] == before
        _assert_searchable(persisted, {"symbol:sample.py::old_first"}, "old_first")
        assert persisted.search_fts("newalpha") == []
    assert not tmp_db.conn.in_transaction


@pytest.mark.parametrize("target,neighbor", [("part_one.py", "partXone.py"), ("part%.py", "part_other.py"), ("Part.py", "part.py")])
def test_replacing_empty_file_only_deletes_its_exact_symbols(tmp_db, tmp_path, target, neighbor):
    # Seed the differently cased filenames directly: macOS filesystems may alias them.
    for filename in (target, neighbor):
        tmp_db.add_entity(
            id=f"symbol:{filename}::stale", name="stale", entity_type="symbol",
            metadata={"file": filename}, embedding=VECTOR,
        )
    _index(tmp_db, tmp_path, "# no remaining definitions\n", target)

    with closing(Storage.open_read_only(tmp_db.db_path)) as persisted:
        _assert_searchable(persisted, {f"symbol:{neighbor}::stale"}, "stale")
        assert persisted.get_entity(f"symbol:{target}::stale") is None


def test_scoped_replacement_removes_legacy_flat_ids(tmp_db, tmp_path):
    tmp_db.add_entity(
        id="symbol:sample.py::run", name="run", entity_type="symbol", embedding=VECTOR,
    )
    _index(tmp_db, tmp_path, "class First:\n    def run(self): pass\n")
    with closing(Storage.open_read_only(tmp_db.db_path)) as persisted:
        _assert_searchable(persisted, {"symbol:sample.py::First.run"}, "run")
        assert persisted.get_entity("symbol:sample.py::run") is None
