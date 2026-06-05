"""TcEx Framework Module"""

# standard library
import json
from typing import TYPE_CHECKING, Any

# first-party
from tcex_app_testing.config_model import config_model

from .profile_output_validation_rules import ProfileOutputValidationRules

if TYPE_CHECKING:
    # first-party
    from tcex_app_testing.profile.profile_runner import ProfileRunner


class ProfileUpdate:
    """Testing Profile Class."""

    def __init__(self, profile: 'ProfileRunner'):
        """Initialize Class properties.

        To reduce the size and complexity of the profile.py module all the update logic is moved
        here. Passing in the entire profile object to be inline with what was there before.
        """
        self.profile = profile

        # properties
        self.ij = profile.ij
        self.log = profile.log
        self.permutation = profile.permutation
        self.redis_client = profile.redis_client
        self.rules = ProfileOutputValidationRules()

    def _generate_output_data(self, outputs: dict, redis_data: dict):
        """Return the outputs section of a profile.

        Args:
            outputs: The dict to add outputs.
            redis_data: The data from KV store for this profile.
        """
        for variable in self.profile.tc_playbook_out_variables:
            # get data from redis for current context
            data = redis_data.get(variable.encode('utf-8'))

            if data is not None:
                # redis return bytes, convert to str and de-serialize
                data = json.loads(data.decode('utf-8'))

            # make business rules based on data type or content
            output_data = {'expected_output': data, 'op': 'eq'}
            if 1 not in self.profile.model.exit_codes:
                output_data = self.rules.generate_rule(data)

            outputs[variable] = output_data

    def _merge_app_inputs(self) -> dict:
        """Merge inputs for Apps."""
        contents = self.profile.contents
        contents['inputs'] = self._merge_inputs()
        return contents

    def _merge_inputs(self) -> dict[str, dict[str, str]]:
        """Merge all config inputs for Apps."""
        inputs = {}
        merged_inputs = {
            'optional': {},
            'required': {},
        }
        for param in self.permutation.inputs_ordered:
            # inputs that are serviceConfig are not applicable for profiles
            if param.service_config is True:
                continue

            # each non hidden input will be checked for permutations if the App has layout
            if param.hidden is False and not self.permutation.validate_input_variable(
                param.name, inputs
            ):
                continue

            # get the correct profile value
            default_value = None if param.type.lower() != 'boolean' else param.default
            profile_value = self.profile.model.get_input(param.name) or default_value

            # get input type based on install.json required field
            required_key = 'optional' if param.required is False else 'required'

            # APP-87 - ensure boolean inputs don't have null values
            if param.type.lower() == 'boolean':
                profile_value = False if not isinstance(profile_value, bool) else profile_value

            # inputs with PBT can't be using in display clause
            if not param.playbook_data_type or param.type.lower() == 'multichoice':
                # update inputs using resolved inputs for next permutation check
                inputs[param.name] = self.profile.model.get_input_resolved(param.name)

            # ensure value for required inputs is not null so
            # that model does not throw a validation error.
            if param.required is True and profile_value is None:
                profile_value = ''

            # store merged/updated inputs for writing back to profile
            merged_inputs[required_key][param.name] = profile_value

        return merged_inputs

    def _output_replacer(self, outputs: dict):
        """Update profile if current profile is not or user specifies --replace_outputs."""
        contents = self.profile.contents
        contents['outputs'] = outputs

        self.profile.rewrite_contents(contents)

    def _output_updater(self) -> dict[str, Any]:
        """Update the outputs and return the updated results."""
        if self.redis_client is None:
            ex_msg = 'Redis client is not defined.'
            raise RuntimeError(ex_msg)

        outputs = {}
        for context in self.profile.context_tracker:
            # get all current keys in current context
            redis_data = self.redis_client.hgetall(context)

            # updated outputs with validation data
            self._generate_output_data(outputs, redis_data)

            # cleanup redis
            self.profile.clear_context(context)

        return outputs

    def exit_message(self):
        """Update validation rules from exit_message section of profile."""
        message_tc = ''
        if config_model.test_case_message_tc_filename.is_file():
            with config_model.test_case_message_tc_filename.open(encoding='utf-8') as mh:
                message_tc = mh.read()

        _contents = self.profile.contents
        if (
            not _contents.get('exit_message')
            or self.profile.pytest_args_model.replace_exit_message
            or self.profile.model.initialized is False
        ):
            # update the profile
            _contents['exit_message'] = {'expected_output': message_tc, 'op': 'eq'}

            self.profile.rewrite_contents(contents=_contents)

    def initialized(self):
        """Update validation rules from exit_message section of profile."""

        _contents = self.profile.contents
        if self.profile.model.initialized is False:
            # update the profile
            _contents['initialized'] = True

            self.profile.rewrite_contents(contents=_contents)

    def merge_inputs(self):
        """Merge new inputs and remove undefined inputs.

        This technically replace inputs, but uses the value from the existing profile.
        """
        if not self.profile.pytest_args_model.merge_inputs:
            return

        contents = self._merge_app_inputs()

        # write updated profile
        self.profile.rewrite_contents(contents=contents)

    def request(self, data: dict):
        """Update the validation rules for outputs section of a profile."""
        if self.profile.pytest_args_model.record:
            deduped_data = {}
            for method, requests in data.items():
                deduped_data[method] = []
                file_names = set()
                for request in requests:
                    if request.get('output_file') not in file_names:
                        deduped_data[method].append(request)
                        file_names.add(request.get('output_file'))
            contents = self.profile.contents
            contents['stage'].setdefault('request', {})
            contents['stage']['request'] = deduped_data

            self.profile.rewrite_contents(contents)

    def outputs(self):
        """Update the validation rules for outputs section of a profile.

        This method gets called in playbook commony during the teardown stage.

        By default this method will only update if the current value is null. If the
        flag --replace_outputs is passed to pytest (e.g., pytest --replace_outputs)
        the outputs will replaced regardless of their current value.
        """
        outputs = self._output_updater()

        if not self.profile.model.outputs or self.profile.pytest_args_model.replace_outputs:
            self._output_replacer(outputs)
