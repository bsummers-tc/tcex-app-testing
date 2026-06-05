# tcex-app-testing — Testing Patterns (`python-test-engineer`)

House-style idioms for the `tests/` suite. New tests must match these so they stay deterministic under
`pytest -n auto` (xdist) and read consistently.

> Layout note: the `tests/` tree **mirrors the package** — a test for `tcex_app_testing/<area>/...` lives
> in `tests/<area>/...`. Create the area dir (and a `conftest.py`/`__init__.py` as needed) when adding the
> first test for an area. pytest, pytest-xdist, deepdiff, and fakeredis are runtime dependencies, so the
> venv's `pytest` is available after `uv sync`.

---

## 1. Parametrize style — **REQUIRED** (mandated standard)

**Every** `@pytest.mark.parametrize` must use the explicit, keyword form below — named `argnames` /
`argvalues`, every case wrapped in `pytest.param(...)` with a human-readable `id=`. Do **not** use the bare
inline-tuple form, positional args, or the comma-string-ids shortcut. A leading comment on each
`pytest.param` describing the case is encouraged.

```python
@pytest.mark.parametrize(
    argnames='value,expected',
    argvalues=[
        pytest.param(
            # plain string passes through
            'blah',
            'blah',
            id='pass-plain-string',
        ),
        pytest.param(
            # empty string is rejected
            '',
            None,
            marks=pytest.mark.xfail(reason='empty not allowed'),
            id='fail-empty-value',
        ),
    ],
)
def test_example(self, value, expected):
    ...
```

Rules:
- `argnames=` is a single comma-separated string; `argvalues=` is a list of `pytest.param(...)`.
- Every `pytest.param` ends with an explicit `id='...'` using lowercase, hyphenated, descriptive slugs
  (e.g. `pass-iv-none`, `fail-empty-value`). Prefix `pass-` / `fail-` when a suite mixes success and error
  cases.
- Positional values in `pytest.param` line up with `argnames` order.
- For expected-failure rows, attach the marker to the row: `pytest.param(..., marks=pytest.mark.xfail(reason='...'), id='...')`.

---

## 2. Reset cached/scoped/registry state between tests

The framework caches via three project descriptors (`registry`, `cached_property`, `scoped_property` from
`tcex_app_testing.pleb`). Fresh-instance fixtures must clear all three first so cached state never leaks
across tests (critical under xdist). When a test class manages its own instance, reset the same three in
`setup_method`.

```python
def _reset_modules():
    registry._reset()
    cached_property._reset()
    scoped_property._reset()
```

---

## 3. fakeredis instead of a live Redis

Redis-backed code is tested against `fakeredis` — never a real server. Swap the KV store's client for a
`fakeredis.FakeRedis()` (globally in `pytest_configure` or via a fixture), and read/assert KV state through
the normal client API.

```python
data = redis_client.hgetall(context)
```

---

## 4. `DeepDiff` for structural comparison

Compare nested dicts / serialized pydantic models with `deepdiff.DeepDiff(..., ignore_order=True)` and
assert the diff is empty with a message naming the subject. Use this instead of brittle field-by-field
equality for JSON-model validation.

```python
ddiff = DeepDiff(
    expected,
    json.loads(model.json(by_alias=True, exclude_defaults=True, exclude_none=True)),
    ignore_order=True,
)
assert not ddiff, f'Failed validation of {name}'
```

---

## 5. Shared test base classes for a family of cases

A test family that repeats setup/validation logic factors it into a base class with
`@staticmethod`/helper methods; concrete test classes subclass it. Reuse an existing base for new cases
rather than re-deriving staging logic.

---

## 6. `monkeypatch` + small mock response classes

Mock API/session behavior with `monkeypatch.setattr(...)`, returning lightweight mock classes that mimic the
real response surface (`.ok`, `.status_code`, `.json()`). Keep reusable mocks beside the tests. Never hit a
live network or real ThreatConnect server.

```python
def mp_post(*args, **kwargs):
    return MockPost({}, ok=False)

monkeypatch.setattr(session, 'post', mp_post)
```

---

## 7. `caplog` for log assertions

Assert on emitted logs with the `caplog` fixture (`caplog.text`, `caplog.records`, `caplog.at_level(...)`)
rather than capturing stdout.

```python
def test_logger_level(caplog: pytest.LogCaptureFixture):
    assert 'DEBUG LOGGING' in caplog.text
    assert any(r.levelno == logging.DEBUG for r in caplog.records)
```

---

## 8. Isolation: `tmp_path` + per-test working directory

Tests that create files take `tmp_path` and build paths under it; use an `autouse` fixture to give each test
its own temp working directory when the code under test writes relative paths. Never write to a
shared/fixed path — it breaks parallel workers.

---

## 9. Assertion messages carry context

Equality assertions include an f-string message echoing actual vs expected so xdist failures are diagnosable
from the summary line alone.

```python
assert result == expected, f'Input {value} result of {result} != {expected}'
```

---

### Layout & determinism (always)
- Mirror the package: a test for `tcex_app_testing/<area>/...` lives in `tests/<area>/...`; create the area
  dir if absent.
- ruff-clean + ruff-formatted (`tests/` is excluded from ty).
- No order dependence, no shared mutable globals, no real network/redis — xdist-safe by construction.
