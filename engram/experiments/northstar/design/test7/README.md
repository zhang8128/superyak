Design-time checks for north-star test 7's auditor (not a run). `sim.py` is the revision-1 reviewer's toy fixture.
The two `power_*.py` scripts compare candidate pair statistics on it, with design seeds disjoint from any plan's.
Run from this directory: `uv run --no-project --with numpy python -I power_lower_quartile.py .`
