"""TcEx Framework Module"""

# standard library
import json
from typing import TYPE_CHECKING, cast

# first-party
from tcex_app_testing.config_model import config_model
from tcex_app_testing.util import Util
from tcex_app_testing.util.code_operation import CodeOperation

if TYPE_CHECKING:
    # first-party
    from tcex_app_testing.profile.profile_runner import ProfileRunner


class ProfileValidate:
    """TcEx Test Module."""

    def __init__(self, profile: 'ProfileRunner'):
        """Initialize Class properties.

        To reduce the size and complexity of the profile.py module all the validator logic is moved
        here. Passing in the entire profile object to be inline with what was there before.
        """
        self.profile = profile

        # properties
        self.log = profile.log
        self.model = profile.model
        self.redis_client = profile.redis_client
        self.util = Util()

    def _file_link(self, needle: str) -> str:
        """Return the line number of the profile in the profile list."""
        # log error for missing output data if not a fail test case (exit code of 1)
        file_link = f'{config_model.test_case_profile_filename_rel}'

        line_number = CodeOperation.find_line_number(
            needle=rf'.*{needle}.*',
            contents=self.profile.contents_raw,
            trigger_start='  "outputs": {',
            trigger_stop='  },',
        )
        if line_number is not None:
            file_link += f':{line_number}'

        return file_link

    def _validate_double_quotes(self, data: str, variable: str):
        """Validate that output is not wrapped in double quotes."""
        # ADI-1118 - log warning if string value is wrapped in quotes
        if isinstance(data, (str)) and data.startswith('"') and data.endswith('"'):
            self.log.warning(
                'step=validate, event=app-data-is-wrapped-in-double-quotes, '
                f'profile-filename="{self._file_link(variable)}"'
            )

    def _validate_null_output(self, context_keys: list[str], variable: str):
        """Validate variable data is not null."""
        # special variable written in tcex.playbook.create._check_null
        variable_null = f'{variable}_NULL_VALIDATION'

        if variable not in context_keys and variable_null not in context_keys:
            self.log.warning(
                f'step=validate, event=app-failed-to-write-variable, variable={variable}, '
                f'profile-filename="{self._file_link(variable)}"'
            )

    def _validate_raw_json(self, variable: str):
        """Validate that output name is not 'raw.json'"""
        if 'raw.json' in variable:
            self.log.warning(
                'step=validate, event=suspect-value-raw-json, '
                f'profile-filename="{self._file_link(variable)}"'
            )

    def _validate_suspect_values(self, data: str, variable: str):
        """Validate that no suspect values are used in the output."""
        suspect_values = ['False', 'null', 'None', 'True']

        if data in suspect_values:
            self.log.warning(
                f'step=validate, event=app-data-matches-suspect-value, value={data}, '
                f'profile-filename="{self._file_link(variable)}"'
            )

    def outputs(self):
        """Iterate over outputs and validate."""
        if self.redis_client is None:
            ex_msg = 'Redis client is not initialized.'
            raise RuntimeError(ex_msg)

        for context in self.profile.context_tracker:
            context_keys = [
                cast('bytes', k).decode('utf-8') for k in self.redis_client.hkeys(context)
            ]
            self.log.info(f'step=validate, event=validate-outputs, context-keys={context_keys}')
            for variable in self.profile.tc_playbook_out_variables:
                # get data from redis for current context
                data = self.redis_client.hget(context, variable.encode('utf-8'))

                # TODO: does this need to use playbooks?
                if data is not None:
                    data = json.loads(data.decode('utf-8'))  # type: ignore

                # validate string-specific checks only when data is a string
                if isinstance(data, str):
                    # check if data is wrapped in double quotes
                    self._validate_double_quotes(data, variable)

                    # check for suspect values in outputs
                    self._validate_suspect_values(data, variable)

                # check for possible null output values, but only if not a fail test case
                if 0 in self.profile.model.exit_codes:
                    self._validate_null_output(context_keys, variable)

                # APP-219 - check for "bad" output variable names
                self._validate_raw_json(variable)

    def validate_profile(self):
        """Validate profile.

        This single method run all validation. It's is made public with profile.validate
        and is currently called from the teardown method in test_case_playbook_common.py.
        """
        self.outputs()
