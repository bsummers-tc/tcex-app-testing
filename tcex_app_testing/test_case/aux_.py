"""TcEx Framework Module"""

# standard library
import json
import logging
import os
import random
import re
import string
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

# third-party
import jmespath
import pytest
import urllib3
from _pytest.config import Config
from _pytest.monkeypatch import MonkeyPatch

# first-party
from tcex_app_testing.app.app import App
from tcex_app_testing.app.config.install_json import InstallJson
from tcex_app_testing.app.playbook import Playbook
from tcex_app_testing.config_model import config_model
from tcex_app_testing.input.model.module_app_model import ModuleAppModel
from tcex_app_testing.input.model.module_requests_session_model import ModuleRequestsSessionModel
from tcex_app_testing.pleb.cached_property import cached_property
from tcex_app_testing.pleb.proxies import proxies
from tcex_app_testing.profile.model.profile_model import ExitMessageModel
from tcex_app_testing.profile.profile_runner import ProfileRunner
from tcex_app_testing.registry import registry
from tcex_app_testing.render.render import Render
from tcex_app_testing.requests_tc import RequestsTc, TcSession
from tcex_app_testing.requests_tc.auth.tc_auth import HmacAuth, TcAuth
from tcex_app_testing.stager import Stager
from tcex_app_testing.util import Util
from tcex_app_testing.validator import Validator

# disable ssl warning message
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# get logger
_logger = logging.getLogger(__name__.split('.', maxsplit=1)[0])


class Aux:
    """Base TestCase Class"""

    def __init__(self):
        """Initialize class properties."""

        # when running testing profile, this is the current test profile
        self._profile_runner: ProfileRunner

        # an instance of the install_json module for access input and outputs
        self.ij = InstallJson(logger=_logger)

        # flag set in setup_class that indicates that the test should be fully initialized
        # and ready to go. this flag is set to False in the teardown_class method.
        self.initialized = False

        # main logger with title and data feature
        self.log = _logger

        # flag to control if the test case should be skipped
        self.skip = False

        # stage data tracker, used to collect and delete staged data.
        self.staged_data = {}

        # the current kv store context, typically defined in setup_method
        # so that each test case has a unique kv store context.
        self.tc_playbook_kvstore_context: str

        # testing context for tcex service Apps
        self.tcex_testing_context = None

        # instance of util method
        self.util = Util()

        # Setting config model so it can be accessed in custom test files.
        self.config_model = config_model

        self.recorded_data = {}

        # add methods to registry
        registry.add_service(App, self.app)
        registry.add_service(RequestsTc, self.session)

    def _log_inputs(self, inputs: dict[str, dict | list | str]):
        """Log inputs masking any that are marked encrypted and log warning for unknown inputs."""
        for name, value in sorted(inputs.items()):
            # get the param data from the install.json file
            input_data = self.ij.model.get_param(name)
            if input_data is None:
                continue

            if name in self.app_inputs_default:
                # log default args with a with a *
                self.log.info(
                    f'step=run, event=create-config, input-name={name}, default-input-value={value}'
                )
            elif input_data.name is None and name not in ['tcex_testing_context']:
                self.log.warning(
                    f'step=run, event=create-config, input-name={name}, unknown-input-value={value}'
                )
            elif input_data.encrypt is True:
                self.log.info(
                    f'step=run, event=create-config, input-name={name}, app-input-value=***',
                )
            else:
                self.log.info(
                    f'step=run, event=create-config, input-name={name}, app-input-value={value}'
                )

    @property
    def _get_tc_playbook_kvstore_context(self) -> str:
        """Generate a unique kv store context for each test case."""
        return os.getenv('TC_PLAYBOOK_DB_CONTEXT', str(uuid4()))

    @property
    def _user_agent(self) -> dict[str, str]:
        """Return a User-Agent string."""
        return {'User-Agent': f'TcExTesting/{__import__(__name__).__version__}'}

    @cached_property
    def app(self) -> App:
        """Return instance of App."""
        return App(self.module_app_model, self.proxies)

    @cached_property
    def app_inputs_default(self) -> dict[str, int | list | str | None]:
        """Return App inputs."""
        _inputs = config_model.inputs

        # using a developer token from the UI is still valid. however,
        # these token expire after a certain amount of time.
        token = os.getenv('TC_TOKEN', self.tc_token)

        # if a token is available, use token over HMAC auth
        if token is not None:
            _inputs['tc_token'] = token
            _inputs['tc_token_expires'] = int(time.time()) + 3600
            del _inputs['tc_api_access_id']
            del _inputs['tc_api_secret_key']

        return _inputs

    def check_environment(self, environments: list, os_environments: list | None = None):
        """Check if test case matches current environments, else skip test."""
        test_envs = environments or ['build']
        os_environments_ = set(os_environments or config_model.os_environments)

        # APP-1212 - fix issue where outputs were being deleted when profile was skipped
        self.skip = False
        if not os_environments_.intersection(set(test_envs)):
            self.skip = True
            pytest.skip('Profile skipped based on current environment.')

    def clear_cache(self):
        """Clear cache."""
        for cache in ['app_inputs_default', 'playbook', 'stager', 'validator']:
            if cache in self.__dict__:
                del self.__dict__[cache]

    def create_config(self, inputs: dict[str, Any]):
        """Create files necessary to start a Service App."""
        config = self.create_config_update(inputs)

        # safely log all inputs to tests.log
        self._log_inputs(config)

        # service Apps will get their input/params from encrypted file in the "in" directory
        data = json.dumps(config, sort_keys=True).encode('utf-8')
        key = ''.join(random.choice(string.ascii_lowercase) for i in range(16))  # nosec
        encrypted_data = self.util.encrypt_aes_cbc(key, data)

        # ensure that the in directory exists
        Path(config['tc_in_path']).mkdir(parents=True, exist_ok=True)

        # write the file in/.app_params.json
        app_params_json = Path(config['tc_in_path']) / '.test_app_params.json'
        with app_params_json.open('wb') as fh:
            fh.write(encrypted_data)

        # when the App is launched the tcex.input module reads the encrypted
        # file created above # for inputs. in order to decrypt the file, this
        # process requires the key and filename to be set as environment variables.
        os.environ['TC_APP_PARAM_KEY'] = key
        os.environ['TC_APP_PARAM_FILE'] = str(app_params_json)

    def create_config_update(
        self, app_inputs: dict[str, int | list | str | None]
    ) -> dict[str, Any]:
        """Update inputs before running App."""

        if self.ij.model.is_playbook_app:
            # set requested output variables
            app_inputs['tc_playbook_out_variables'] = self.profile_runner.tc_playbook_out_variables
            app_inputs['tc_playbook_kvstore_context'] = self.tc_playbook_kvstore_context

        # update default inputs with app inputs
        _app_inputs = self.app_inputs_default.copy()
        _app_inputs.update(app_inputs)

        # update path inputs from profile
        # service Apps do not have a profile when this is needed.
        _app_inputs['tc_in_path'] = str(config_model.test_case_tc_in_path)
        _app_inputs['tc_log_path'] = str(config_model.test_case_tc_log_path)
        _app_inputs['tc_out_path'] = str(config_model.test_case_tc_out_path)
        _app_inputs['tc_temp_path'] = str(config_model.test_case_tc_temp_path)

        return _app_inputs

    def init_profile(
        self,
        app_inputs: dict[str, str],
        monkeypatch: MonkeyPatch,
        profile_name: str,
        pytestconfig: Config,
    ):
        """Stages and sets up the profile given a profile name"""

        self.log.info(f'step=run, event=init-profile, profile={profile_name}')
        self._profile_runner = ProfileRunner(
            app_inputs=app_inputs,
            monkeypatch=monkeypatch,
            pytestconfig=pytestconfig,
            redis_client=self.app.key_value_store.redis_client,
            tcex_testing_context=self.tcex_testing_context,
        )

        # this value is not set at the time that the stager/validator is
        # initialized. setting it now should be soon enough for everything
        # to work properly.
        if self.ij.model.is_playbook_app:
            self.playbook.output_variables = self._profile_runner.tc_playbook_out_variables

        # Override test environments if specified
        os_environments = None
        if pytestconfig:
            os_environments = pytestconfig.option.environment

        # check profile environment
        self.check_environment(self._profile_runner.model.environments, os_environments)

        # merge profile inputs (add new / remove non-defined)
        self._profile_runner.update.merge_inputs()

        # stage kvstore data based on current profile
        self.stage_data()

    def stage_and_replace(self, stage_key, data, stage_function, fail_on_error=True):
        """Stage and replace data."""
        staged_data = stage_function(data) if data is not None else stage_function()
        self.staged_data.update({stage_key: staged_data})
        self.replace_variables(fail_on_error=fail_on_error)

    def stage_data(self):
        """Stage data for current profile."""

        self.stage_and_replace('env', None, self.stager.env.stage_model_data, fail_on_error=False)
        request_data = self._profile_runner.data.get('stage', {}).get('request', {})
        if self._profile_runner.pytest_args_model.record:
            self.stager.request.record_all(self.recorded_data)
        else:
            self.stager.request.stage(request_data)
        vault_data = self._profile_runner.data.get('stage', {}).get('vault', {})
        self.stage_and_replace('vault', vault_data, self.stager.vault.stage, fail_on_error=False)
        tc_data = self._profile_runner.data.get('stage', {}).get('threatconnect', {})
        self.stage_and_replace('tc', tc_data, self.stager.threatconnect.stage, fail_on_error=True)
        self.stager.redis.from_dict(self._profile_runner.model_resolved.stage.kvstore)

    def log_staged_data(self):
        """Log staged data."""
        staged_data = ['----Staged Data Keys----']
        for key, value in self.staged_data.items():
            staged_data.append(f'---{key}---')
            if key.lower() == 'env':
                staged_data.extend(sorted(value.keys()))
            else:
                value_ = sorted({k_ for k_, v_ in self.flatten_dict(value).items() if v_})
                staged_data.extend(value_)
        self.log.info('step=run, event=staged-data')
        self.log.info('\n'.join(staged_data))
        Render.panel.info('\n'.join(staged_data))

    def flatten_dict(self, d, parent_key='', separator='.') -> dict:
        """Flatten a nested dictionary."""
        items = []
        for key, value in d.items():
            new_key = f'{parent_key}{separator}{key}' if parent_key else key
            if isinstance(value, dict):
                items.extend(self.flatten_dict(value, new_key, separator=separator).items())
            else:
                items.append((new_key, value))
        return dict(items)

    def replace_variables(self, fail_on_error=True, prefixes=None):
        """Replace variables in profile with staged data."""
        if prefixes is None:
            prefixes = ['env', 'tc', 'vault']

        profile_dict = self._profile_runner.model.dict()
        outputs_section = profile_dict.pop('outputs', {})
        profile = json.dumps(profile_dict)

        for m in re.finditer(r'\${(.*?)}', profile):
            full_match = str(m)
            try:
                full_match = m.group(0)
                jmespath_expression = m.group(1)
                jmespath_expression = jmespath_expression.encode().decode('unicode_escape')

                if not any(jmespath_expression.startswith(f'{prefix}.') for prefix in prefixes):
                    continue

                value = jmespath.search(jmespath_expression, self.staged_data)

                if not value and not fail_on_error:
                    continue

                if not value:
                    self.log_staged_data()
                    self.log.error(
                        f'step=run, event=replace-variables, error={full_match} '
                        'could not be resolved.'
                    )
                    Render.panel.failure(f'Jmespath for {full_match} was invalid value: {value}.')

                profile = profile.replace(full_match, str(value))
            except Exception:
                self.log_staged_data()
                if fail_on_error:
                    self.log.exception(f'step=run, event=replace-variables, error={full_match}')
                    Render.panel.failure(f'Invalid variable/jmespath found {full_match}.')
                else:
                    self.log.warning(
                        f'step=run, event=replace-variables-non-fatal, error={full_match}'
                    )
        profile_dict = json.loads(profile)
        profile_dict['outputs'] = outputs_section
        self._profile_runner.data = profile_dict

    @cached_property
    def module_app_model(self) -> ModuleAppModel:
        """Return the Module App Model."""
        return ModuleAppModel(**config_model.dict())

    @cached_property
    def module_requests_session_model(self) -> ModuleRequestsSessionModel:
        """Return the Module App Model."""
        return ModuleRequestsSessionModel(**config_model.dict())

    @property
    def profile_runner(self) -> ProfileRunner:
        """Return profile instance."""
        return self._profile_runner

    @cached_property
    def proxies(self) -> dict:
        """Format the proxy configuration for Python Requests module.

        Generates a dictionary for use with the Python Requests module format
        when proxy is required for remote connections.

        **Example Response**
        ::

            {'http': 'http://user:pass@10.10.1.10:3128/'}
        """
        return proxies(
            proxy_host=config_model.tc_proxy_host,
            proxy_port=config_model.tc_proxy_port,
            proxy_user=config_model.tc_proxy_username,
            proxy_pass=config_model.tc_proxy_password,
        )

    def cleanup(self):
        """Cleanup staged data."""
        self.stager.threatconnect.cleanup(self.staged_data.get('tc', {}))

    @cached_property
    def session(self) -> RequestsTc:
        """Return requests Session object for TC admin account."""
        return RequestsTc(self.module_requests_session_model)

    @cached_property
    def session_exchange(self) -> TcSession:
        """Return requests Session object for TC admin account.

        The credential this session uses require special activation in the ThreatConnect Platform
        and is not intended for normal use.
        """
        auth = HmacAuth(
            tc_api_access_id=config_model.tc_api_access_id,
            tc_api_secret_key=config_model.tc_api_secret_key,
        )
        return self.session.get_session(
            auth=auth,
            base_url=config_model.tc_api_path,
            log_curl=config_model.tc_log_curl,
            proxies=self.proxies,
            proxies_enabled=config_model.tc_proxy_tc,
            verify=config_model.tc_verify,
        )

    @cached_property
    def session_tc(self) -> TcSession:
        """Return requests Session object for TC admin account."""
        auth = TcAuth(
            tc_api_access_id=config_model.tc_api_access_id,
            tc_api_secret_key=config_model.tc_api_secret_key,
            tc_token=self.tc_token,
        )
        return self.session.get_session(
            auth=auth,
            base_url=config_model.tc_api_path,
            log_curl=config_model.tc_log_curl,
            proxies=self.proxies,
            proxies_enabled=config_model.tc_proxy_tc,
            verify=config_model.tc_verify,
        )

    @cached_property
    def stager(self):
        """Return instance of Stager class."""
        return Stager(self.playbook, self.app.key_value_store.redis_client, self.session_tc)

    @property
    def tc_token(self):
        """Return a valid API token."""
        if config_model.tc_api_path is None:  # no API path, no token
            return None

        data = None
        http_success = 200
        token = None
        # defaulting to api token
        token_type = 'api'  # nosec

        # retrieve token from API using HMAC auth
        r = self.session_exchange.post(f'/internal/token/{token_type}', json=data, verify=True)
        if r.status_code == http_success:
            token = r.json().get('data')
            self.log.info(
                f'step=setup, event=using-token, '
                f'token=***{token[-4:] if token else ""}, token-elapsed={r.elapsed}'
            )
        else:
            self.log.error(f'step=setup, event=failed-to-retrieve-token error="{r.text}"')
        return token

    def validate_exit_message(self, exit_message_data: ExitMessageModel):
        """Validate App exit message."""
        # convert model to dict
        exit_message_dict = exit_message_data.dict()
        test_exit_message = exit_message_dict.pop('expected_output')
        op = exit_message_dict.pop('op')

        if test_exit_message is not None:
            app_exit_message = None
            if config_model.test_case_message_tc_filename.is_file():
                with config_model.test_case_message_tc_filename.open(encoding='utf-8') as mh:
                    app_exit_message = mh.read()

                if app_exit_message:
                    exit_message_dict['title'] = 'Exit Message Validation'
                    exit_message_dict['log_app_data'] = json.dumps(app_exit_message)
                    if op == 'eq':
                        exit_message_dict['log_test_data'] = json.dumps(test_exit_message)

                    # compare
                    passed, assert_error = self.validator.compare(
                        app_exit_message, test_exit_message, op=op, **exit_message_dict
                    )
                    assert passed, assert_error  # nosec
                else:
                    pytest.fail('The message.tc file was empty.')
            else:
                pytest.fail(
                    f'No message.tc file found at ({config_model.test_case_message_tc_filename}).'
                )

    @property
    def validator(self):
        """Return instance of Stager class."""
        return Validator(
            self.playbook,
            self.app.key_value_store.redis_client,
            self.session_tc,
            config_model.tc_temp_path,
        )

    @cached_property
    def playbook(self) -> Playbook:
        """Return an instance of Playbooks module."""
        # playbook is first used in the setup_method call for the stager
        # and at that point self.profile has not been initialized and
        # the self.profile.tc_playbook_out_variable array is not available.
        return self.app.get_playbook(
            context=self.tc_playbook_kvstore_context,
            output_variables=[],
        )
