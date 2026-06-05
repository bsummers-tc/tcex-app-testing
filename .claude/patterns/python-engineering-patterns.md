# tcex-app-testing — Engineering Patterns (`python-engineer`)

House-style idioms that recur across the TcEx App Testing Framework. When you add or modify framework
code, match the relevant pattern below so the change is indistinguishable from the surrounding code.
These are **observed, enforced conventions** — not generic advice. Each entry cites real files under
`tcex_app_testing/`.

> Scope note: this project has **no generated code and no code generator**. All Python under
> `tcex_app_testing/` is hand-written and edited directly.

---

## 1. Module-level logger via the top-level package name

Every module that logs binds a module-scoped `_logger` by splitting `__name__` on the first dot, so all
records route through the single top-level logger hierarchy (and the custom `TraceLogger`). Do **not** call
`logging.getLogger(__name__)` (full dotted path) — always the top-level segment.

`requests_tc/requests_tc.py`, `requests_tc/tc_session.py`, `validator/validator.py`,
`validator/validator_abc.py`, `logger/__init__.py`.

```python
# standard library
import logging

# first-party
from tcex_app_testing.logger.trace_logger import TraceLogger

_logger: TraceLogger = logging.getLogger(__name__.split('.', maxsplit=1)[0])  # type: ignore
```

Use the bare `_logger = logging.getLogger(__name__.split('.', maxsplit=1)[0])` form when the `TraceLogger`
annotation/`trace()` calls are not needed; add the annotated form (with `# type: ignore`) when the module
calls `_logger.trace(...)`.

---

## 2. Lazy attributes: `cached_property` vs `scoped_property` (from `tcex_app_testing.pleb`)

Two project-specific descriptors back almost all lazily-built attributes. **Pick by lifetime**, and always
import from `tcex_app_testing.pleb` (not `functools`) so the suite's `_reset()` can clear them between tests.

- `from tcex_app_testing.pleb.cached_property import cached_property` — compute once per instance, cache for
  the instance's life. Use for inputs-derived helpers, sub-APIs, parsed files.
  (`requests_tc/requests_tc.py`, `validator/validator.py`, `app/config/app_spec_yml.py`,
  `app/config/layout_json.py`.)
- `from tcex_app_testing.pleb.scoped_property import scoped_property` — thread/process-aware caching that
  detects process forking; use for per-execution resources that must not leak across threads/forks
  (session, KV store).

```python
from tcex_app_testing.pleb.cached_property import cached_property

@cached_property
def session(self) -> TcSession:
    """Return an authenticated ThreatConnect session."""
    return TcSession(...)
```

> The shared `registry` (`tcex_app_testing/registry.py`) is a dependency-injection primitive used at the top
> of the object graph. It is **not** a routine pattern — only wire into it when extending the top-level
> composition, and follow the existing `@registry.factory(...)` usage exactly.

---

## 3. pydantic **v1** model `Config` conventions

Config-/install-json-facing models share a consistent inner `Config`: a `snake_to_camel` alias generator
(Python snake_case attrs ↔ camelCase JSON), `validate_assignment = True`, and an explicit `Extra` policy.
Match the **same `Extra`** the neighboring models use (`allow` for install.json passthrough, `forbid`/`ignore`
where the surface is closed).

`app/config/model/install_json_model.py`, `app/config/model/layout_json_model.py`,
`app/config/model/app_spec_yml_model.py`, `app/config/model/job_json_model.py`.

```python
from pydantic import BaseModel, Extra
from tcex_app_testing.util.string_operation import snake_to_camel

class Config:
    """DataModel Config"""
    alias_generator = snake_to_camel
    validate_assignment = True
    extra = Extra.allow
```

When serializing v1 models, use the v1 kwargs the codebase relies on:
`model.json(by_alias=True, exclude_defaults=True, exclude_none=True)` / `.dict(by_alias=True)`.

---

## 4. Custom field types: `__get_validators__` chain

Custom input field types subclass a builtin and expose a validator **chain** from `__get_validators__`,
each step a `@classmethod (cls, value, field: ModelField) -> value` that raises a custom exception on
failure and otherwise returns the (possibly transformed) value. Order matters — type check first, then
transforms, then constraint checks.

`input/field_type/sensitive.py` (the `Sensitive` type — note this type protects secret values, so it must
never log or `repr` its contents).

```python
class Sensitive:
    @classmethod
    def __get_validators__(cls) -> Generator:
        yield cls.validate_type
        yield cls.validate_allow_empty
    ...
```

---

## 5. Custom exception hierarchy with `field_name` + logging

Validation/runtime errors subclass a small base that **logs on construction** and carries a `field_name`
for tracing which field failed. Subclasses only build the message. Raise these (never bare `ValueError`)
from field validators.

`input/field_type/exception.py`.

```python
class BaseValueError(ValueError):
    def __init__(self, field_name: str, message: str):
        _logger.debug(f'Checking value for field {field_name}: {message}')
        super().__init__(message)
```

---

## 6. Self-referential models: `update_forward_refs()`

Recursive models declare the forward ref and call `update_forward_refs()` at module bottom (v1 requirement).
Do this for any model that references itself or a not-yet-defined sibling.

`app/config/model/layout_json_model.py`.

```python
class Parameter(BaseModel):
    ...

Parameter.update_forward_refs()
```

---

## 7. Composed input models via focused mixins

The runtime input model is assembled from focused mixin models (`ApiModel`, `ProxyModel`, `PathModel`,
`PlaybookCommonModel`, …) rather than one monolithic model. Add new input surface as a focused mixin and
compose it — do not bolt fields onto an umbrella model directly.

`input/model/api_model.py`, `input/model/proxy_model.py`, `input/model/path_model.py`,
`input/model/playbook_common_model.py`, `input/model/module_app_model.py`.

---

## 8. Interface via ABC + runtime implementation selection

Pluggable subsystems define an `ABC` with `@abstractmethod`s, and a holder picks the concrete
implementation at runtime behind a `cached_property` (redis / api / mock). Add a new backend by
implementing the ABC and extending the selector — keep the public method surface identical to the ABC.

`app/key_value_store/key_value_abc.py`, `validator/validator_abc.py`, `profile/migration/migration.py`.

```python
class KeyValueABC(ABC):
    @abstractmethod
    def create(self, context: str, key: str, value: Any) -> int: ...
```

---

## 9. Conditional/late imports for heavy or app-type-specific modules

Branch-selected heavy modules are imported **inside** the property/method that needs them, with
`# noqa: PLC0415`, to avoid hard import-time dependencies. Use this only for genuinely conditional/heavy
imports — normal imports stay at module top, isort-ordered into `# standard library` / `# third-party` /
`# first-party` blocks.

`test_case/test_case_playbook.py`.

---

### Import-block convention (applies everywhere)

Imports are grouped and commented in three isort sections; keep the comments:

```python
# standard library
import logging

# third-party
from pydantic import BaseModel

# first-party
from tcex_app_testing.pleb.cached_property import cached_property
```
