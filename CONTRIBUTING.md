# Contributing

Thanks for helping improve Forza-Telemetry-Helper!

## Development setup

```sh
git clone https://github.com/molotovah/Forza-Telemetry-Helper.git
cd Forza-Telemetry-Helper
pip install -e ".[dev]"
pytest -q        # tests
ruff check .     # lint
```

No game required: use `fth.fixtures.make_packet()` for synthetic telemetry in tests.

## Guidelines

- Keep dependencies minimal; prefer the standard library.
- Every non-trivial change ships with a test.
- Python code is formatted/linted with ruff (`line-length = 100`).
- Documentation and commit messages in English.
- One feature or fix per pull request; keep diffs reviewable.

## Reporting issues

Include: FH6 platform (PC/Xbox), Python version, OS, relevant log output, and if
possible a short CSV snippet of recorded telemetry (no personal data).
