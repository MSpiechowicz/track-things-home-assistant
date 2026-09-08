# Track Things for Home Assistant

Custom integration for [Track Things](https://track-things.com).
The repository provides loading/unloading, an asynchronous API client, pure
dynamic-field validation, pure calendar mapping, a Home Assistant test harness,
source-quality checks, and CI. Account setup, workspace selection, and reauthentication
are available in the integration UI, along with tracker selection and five-minute
metadata discovery. See the [metadata guide](docs/METADATA.md). A read-only
workspace calendar is available in Home Assistant; see the [calendar guide](docs/CALENDAR.md).
Daily-calendar and refresh actions are available; see the [action guide](docs/CALENDAR_ACTIONS.md).
Manual entry creation is available through the [create-entry action](docs/CREATE_ENTRY_ACTION.md).
A [Google Home daily-summary shortcut blueprint](docs/GOOGLE_DAILY_SUMMARY.md)
is available for a configured fixed speaker; real-device verification remains pending.
Full conversational voice commands remain planned and are **not available yet**.

See the [implementation plan](docs/IMPLEMENTATION_PLAN.md) and the
[project board](https://github.com/users/MSpiechowicz/projects/4).

The [account setup guide](docs/ACCOUNT_SETUP.md) documents HTTPS/local-development
configuration, session storage, reauthentication, and verification.

The [API client guide](docs/API_CLIENT.md) documents resource methods, authentication,
pagination, retries, errors, and offline verification.
The [schema validation guide](docs/SCHEMA_VALIDATION.md) documents backend-compatible
value validation, conditional visibility, and explicit draft normalization.

The [calendar mapping guide](docs/CALENDAR_MAPPING.md) documents historical event
presentation, timezone overlap, and the offline fixture replay.

The integration bundles the Track Things app icon in `brand/icon.png`, served
locally by Home Assistant. Keep the `brand` directory when copying the integration.

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
entries and real config flows; HTTP responses are synthetic. No running backend, credentials,
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

Add Track Things through Settings → Devices & services → Add integration.
Choose the account connection option and sign in with Google, GitHub, or your
usual method in the browser. The production backend URL is automatic. See
[account setup](docs/ACCOUNT_SETUP.md) for approval, revocation, and advanced setup.
Empty YAML remains a development-only loading check and takes no account
settings. Do not put tokens or passwords in YAML.

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
Things adds an account config flow and a read-only calendar for configured workspaces. The lifecycle tests
cover authenticated config-entry setup/reload/unload.

## Scope of the planned integration

- Read the recorded-entry calendar, including multi-day entries.
- Add entries using existing tracker schemas, with subject/detail clarification
  and confirmation through English and Polish Home Assistant Assist pipelines.
- Use one Track Things account/workspace per instance, including Google and GitHub SSO.
- Offer Google Home fixed-script shortcuts and configured-speaker summaries.

Google Home shortcuts do not forward arbitrary speech or follow-up replies into
Assist. Full dialogue will use Assist. Backend authentication, date filtering,
schema guards, and idempotency are prerequisite tickets; no backend changes are
included in this scaffold.

## Automatic versioning

After both CI jobs pass on a push to `main`, the version job reads Conventional
Commits since the highest reachable stable `vX.Y.Z` tag:

- `feat:` increments minor.
- `fix:`, `perf:`, and `revert:` increment patch.
- `!` in a Conventional Commit header or a `BREAKING CHANGE:` /
  `BREAKING-CHANGE:` footer increments major, including before version 1.0.
- Documentation, tests, chores, refactors, and unrecognized subjects do not bump
  unless they declare a breaking change. The highest increment wins.

The job updates `project.version` in `pyproject.toml` and `version` in the Home
Assistant manifest together, commits as `github-actions[bot]`, and atomically
pushes the commit and annotated `vX.Y.Z` tag. Before the first tag it uses the
stored `0.1.0` as the base and examines all commits; the initial `feat:` therefore
produces `0.2.0`. Keep both files synchronized and do not bump them manually.

Preview locally without modifying files:

```sh
python scripts/semantic_version.py
```

PRs and branch builds only preview. When squash-merging, use a Conventional
Commit PR title (for example `feat: add calendar support`) so the resulting main
commit declares the intended change. Merge commits can retain the conventional
subjects of the individual commits.

Only the version job has `contents: write`. It uses the built-in `GITHUB_TOKEN`,
which does not trigger another push workflow; the release commit also contains
`[skip ci]`. Serialized jobs skip stale tested commits and never force-push. An
atomic push fails if main changes or a tag conflicts, leaving the remote unchanged.
A retry after a successful release finds nothing new to bump.

Repository/organization rules must permit the Actions token to push the version
commit to `main` and create tags; this workflow does not bypass branch protection.
No PyPI upload or GitHub Release publication is included.

## Conversation drafts

The pure draft state machine supports typed detail updates, isolated sessions,
review, and explicit revision-bound confirmation. See
[the adapter contract and offline replay](docs/CONVERSATION_DRAFTS.md).

## License

GPL-3.0-only; see [LICENSE](LICENSE).

Name-based recording and voice-adapter discovery are documented in the [name-based action guide](docs/NAME_BASED_ACTIONS.md).
