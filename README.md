# Track Things for Home Assistant

Custom integration scaffold for [Track Things](https://track-things.com).
This first increment provides loading/unloading, a Home Assistant test harness,
source-quality checks, and CI. Account setup, calendar entities, and voice commands
are planned features and are **not available yet**.

See the [implementation plan](docs/IMPLEMENTATION_PLAN.md) and the
[project board](https://github.com/users/MSpiechowicz/projects/4).

## Development

Use **Python 3.14.2 or newer**. The minimum Home Assistant version is **2026.9.0**.
The custom-component test harness pins Home Assistant and its testing dependencies
as a compatible set; do not override its Home Assistant pin independently.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pip check
python -m pytest -q tests/test_init.py tests/test_source_quality.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

Tests load the real custom component through Home Assistant and use mock config
entries; only the future config-flow platform/handler is stubbed, since Home
Assistant requires it for synthetic entries. No running backend, credentials,
or microphone is required. Internet
sockets are disabled during tests, with Unix sockets allowed for the event loop.
Home Assistant's fixture teardown also checks for leaked tasks and resources.

To reproduce the minimum-version CI job, create a second environment:

```sh
python -m venv .venv-minimum
source .venv-minimum/bin/activate
python -m pip install -e ".[test]" -c constraints/minimum.txt
python -m pip check
python -m pytest -q
```

CI runs these checks on pushes, pull requests, and weekly. Its minimum job pins
Home Assistant 2026.9.0 with harness 0.13.363; its latest job resolves the newest
stable compatible harness (2026.9.1 / 0.13.364 when bootstrapped). Review future
Python/runtime requirements when advancing the compatibility baseline. Updating
the harness and Home Assistant must be done together.

Keep handwritten source and test files at or below **500 physical lines**. Split
by responsibility instead of compressing code. The checker covers Python,
JavaScript/TypeScript, CSS, and shell files, including untracked files. It excludes
virtual environments, caches, build outputs, vendored/generated directories, and
symlinks. JSON data, Markdown documentation, and other assets are not source files
for this check. Use `python -m ruff format .` to format changed Python files.

## Disposable-instance smoke test

This scaffold has no config flow, so it does not appear as an addable integration
in the UI. Empty YAML is a temporary development-only loading path and takes no
account settings. Do not put tokens or passwords in it.

After installing the minimum-version test environment above, run the following
from the repository root. The directory created here is disposable and contains
Home Assistant state; never commit its contents.

```sh
smoke_config=$(mktemp -d)
mkdir -p "$smoke_config/custom_components"
cp -R custom_components/track_things "$smoke_config/custom_components/"
printf 'track_things: {}\nhttp:\n  server_host: 127.0.0.1\n  server_port: 18123\n' \
  > "$smoke_config/configuration.yaml"
python -m homeassistant --config "$smoke_config" --script check_config
python -m homeassistant --config "$smoke_config" --verbose
```

Wait for `Setup of domain track_things took ... seconds`, then press Ctrl+C.
Run the final command a second time and confirm the integration loads again with
no import/setup errors. Home Assistant's standard warning about an untested custom
integration is expected. First startup downloads Home Assistant's additional
runtime dependencies and can take a few minutes; do not use `--skip-pip` in a
fresh environment. Its HTTP server is bound to loopback on port 18123. Track
Things adds no UI or entities yet. The lifecycle tests cover config-entry
setup/reload/unload before the account config flow is implemented.

## Scope of the planned integration

- Read the recorded-entry calendar, including multi-day entries.
- Add entries using existing tracker schemas, with subject/detail clarification
  and confirmation through English and Polish Home Assistant Assist pipelines.
- Use one password-authenticated Track Things account/workspace per instance.
- Offer Google Home fixed-script shortcuts and configured-speaker summaries.

Google Home shortcuts do not forward arbitrary speech or follow-up replies into
Assist. Full dialogue will use Assist. Backend authentication, date filtering,
schema guards, and idempotency are prerequisite tickets; no backend changes are
included in this scaffold.

## License

GPL-3.0-only; see [LICENSE](LICENSE).
