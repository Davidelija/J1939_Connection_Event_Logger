# j1939-logger

J1939 diagnostic-port connected-devices event logger (SYSE 549 project, Colorado State University).

- Specs: `docs/` (start with `docs/handoff.md`). From Tuesday, Nov 10, 2026, `docs/` is the only copy: the Claude Docs, Word and text versions are frozen and superseded.
- Background: `docs/background/` (Beacon doc, detection doc, architecture page)
- For the recipient: `docs/transition.md`, then the no-hardware demo (`demo/run_demo.sh`, Linux machine or VM), `docs/user-manual.md` and `docs/porting.md`
- Module map (what each module and script is for, and its status): `docs/module-map.md`
- Rules for Claude Code: `CLAUDE.md`
- Licence: MIT (`LICENSE`), provided without support after the semester
- Status: build step 1 complete (receive-only pipeline on `vcan0`: a new device gives a chained `connection_start` within 2 s); build step 2 (sessions and chain) in progress.

## Development

Python 3.9 or later (CI runs 3.9, DC-1). The logger itself uses only the standard library; the dev tools are pinned by version in `pyproject.toml` and by hash in `requirements/dev.txt`.

```bash
python -m pip install --require-hashes -r requirements/dev.txt
export PYTHONPATH=src
ruff format --check . && ruff check . && mypy && lint-imports
python -m pytest --cov
python tools/check_verification.py --mode staged
```

The CAN tests need Linux with `vcan0` up (`sudo modprobe vcan; sudo ip link add dev vcan0 type vcan; sudo ip link set up vcan0`); elsewhere they are skipped.
