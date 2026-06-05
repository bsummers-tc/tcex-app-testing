"""TcEx Framework Module"""

# standard library
import json
from typing import cast

# third-party
from _pytest.config import Config as PytestConfig
from _pytest.monkeypatch import MonkeyPatch
from redis import Redis

# first-party
from tcex_app_testing.pleb.cached_property import cached_property
from tcex_app_testing.profile.model.pytest_args_model import PytestArgsModel
from tcex_app_testing.profile.profile import Profile
from tcex_app_testing.profile.profile_migrate import ProfileMigrate
from tcex_app_testing.profile.profile_update import ProfileUpdate
from tcex_app_testing.profile.profile_validate import ProfileValidate


class ProfileRunner(Profile):
    """Testing Profile Class.

    Args:
        app_inputs: The default Args for the profile.
        monkeypatch: Pytest monkeypatch object.
        pytestconfig: Pytest config object.
        redis_client: An instance of Redis client.
        tcex_testing_context: The current context for this profile.
    """

    def __init__(
        self,
        app_inputs: dict,
        monkeypatch: MonkeyPatch,
        pytestconfig: PytestConfig,
        redis_client: Redis,
        tcex_testing_context: str | None = None,
    ):
        """Initialize instance properties."""
        super().__init__()
        self._app_inputs = app_inputs
        self.redis_client = redis_client
        self.pytestconfig = pytestconfig
        self.monkeypatch = monkeypatch
        self.tcex_testing_context = tcex_testing_context

        # properties
        self.update = ProfileUpdate(self)

    @cached_property
    def pytest_args_model(self):
        """Return dict of pytest config args."""
        return PytestArgsModel(
            merge_inputs=self.pytestconfig.option.merge_inputs,
            replace_exit_message=self.pytestconfig.option.replace_exit_message,
            replace_outputs=self.pytestconfig.option.replace_outputs,
            record=self.pytestconfig.option.record,
        )

    def clear_context(self, context):
        """Clear all context data in redis.

        Args:
            context (str): The context (session_id) to clear in KV store.
        """
        keys = self.redis_client.hkeys(context)
        if keys:
            return self.redis_client.hdel(context, *keys)
        return 0

    @cached_property
    def contents(self) -> dict:
        """Return the contents of the current profile file.

        Any time the rewrite_contents method is called, this cached property will be
        reset so that the next time it's accessed the latest data is pulled from file.
        """
        contents = json.loads(self.contents_raw)
        contents, migrated = ProfileMigrate().migrate_schema(contents)
        if migrated is True:
            self.rewrite_contents(contents)
            contents = json.loads(self.contents_raw)
        self.log.debug(f'event=contents-loaded, migrated={migrated}')

        return contents

    @property
    def context_tracker(self) -> list[str]:
        """Return the current context trackers for Service Apps."""
        if not self._context_tracker and self.tcex_testing_context:
            # redis_client is synchronous, so hget never returns an Awaitable
            context_tracker = cast(
                'str | None',
                self.redis_client.hget(self.tcex_testing_context, '_context_tracker'),
            )
            self._context_tracker = json.loads(context_tracker or '[]')
        return self._context_tracker

    def validate(self):
        """Run profile validation methods.

        This is typically called from the teardown
        method of test case playbook common.
        """
        ProfileValidate(self).validate_profile()
