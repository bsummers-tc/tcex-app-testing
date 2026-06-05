"""TcEx Framework Module"""

# standard library
import contextlib
import datetime
import difflib
import hashlib
import json
import logging
import numbers
import operator
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable

# third-party
from deepdiff import DeepDiff

# first-party
from tcex_app_testing.util import Util
from tcex_app_testing.util.variable import StringVariable

# get logger
_logger = logging.getLogger(__name__.split('.', maxsplit=1)[0])


class ValidatorABC(ABC):
    """Validator"""

    def __init__(self):
        """Initialize class properties."""

        # properties
        self.log = _logger
        self.max_diff = 10
        self.util = Util()

    @staticmethod
    def _load_json_data(data: str | list | dict) -> dict | list:
        """Load json data."""
        if isinstance(data, str):
            return json.loads(data)

        if isinstance(data, list):
            # ADI-1076/ADI-1149
            data_updated = []
            for ad in data:
                ad_ = ad
                if isinstance(ad_, (OrderedDict | dict)):
                    ad_ = json.dumps(ad_)

                with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                    # APP-599 - best effort try to stringify value in list
                    ad_ = json.loads(ad_)

                data_updated.append(ad_)
            return data_updated
        return data

    def _basic_operator(
        self,
        app_data: float | str | None,
        test_data: float | str | None,
        op: Callable,
    ) -> tuple[bool, str]:
        """Compare app data is less than or equal to tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
            op: The operator to use for comparison (e.g., operator.le).
        """
        if app_data is None:
            return False, f'Invalid app_data: {app_data}. App Data can not be null.'

        if test_data is None:
            return False, f'Invalid test_data: {test_data}. Test Data can not be null.'

        app_data = self._string_to_int_float(app_data)
        test_data = self._string_to_int_float(test_data)
        results = op(app_data, test_data)
        details = ''
        if not results:
            op_name = getattr(op, '__name__', str(op))
            details = f'{app_data} {type(app_data)} !({op_name}) {test_data} {type(test_data)}'
        return results, details

    @staticmethod
    def _string_to_int_float(x: bytes | float | str | None) -> float | int | str | None:
        """Take string input and return float or int.

        Args:
            x: The value to coerce to float/int.
        """
        if x is None:
            return x

        x = x.decode('utf-8') if isinstance(x, bytes) else x
        try:
            f = float(x)
            i = int(f)
        except TypeError:
            return x  # pyright: ignore reportGeneralTypeIssues
        except ValueError:
            return x  # pyright: ignore reportGeneralTypeIssues

        if f != i:
            return f  # return float
        return i  # return int

    @staticmethod
    def check_null(data_list: float | list | str | None) -> bool:
        """Check if data_list is None or if None exists in the data_list."""
        data_list = data_list if isinstance(data_list, list) else [data_list]

        return any(data is None for data in data_list)

    def details(
        self,
        app_data: dict | float | list | str | None,
        test_data: dict | float | list | str | None,
        op: str,
    ) -> str:
        """Return details about the validation."""
        details = ''

        # ndiff can only handle strings
        if not isinstance(app_data, str) or not isinstance(test_data, str):
            return details

        # the only supported operator types for ndiff are string equality
        if op not in ['eq', 'ne']:
            return details

        try:
            diff_count = 0
            for i, diff in enumerate(difflib.ndiff(app_data, test_data)):
                if diff[0] == ' ':  # no difference
                    continue

                if diff[0] == '-':
                    details += f'\n    * Missing data at index {i}'
                elif diff[0] == '+':
                    details += f'\n    * Extra data at index {i}'
                if diff_count > self.max_diff:
                    details += '\n    * Max number of differences reached.'
                    # don't spam the logs if string are vastly different
                    self.log.error('step=validate, event=max-number-of-differences-reached')
                    break
                diff_count += 1
        except (TypeError, KeyError) as e:
            self.log.warning(f'step=validate, event=diff-computation-failed, error={e}')
        return details

    def operator_date_format(self, app_data: list | str, test_data: str) -> tuple[bool, str]:
        """Validate that app data matches a date format or a list of date formatted strings.

        Args:
            app_data: One or more date strings.
            test_data: A strptime string for comparison.
        """
        # this code should be unreachable, but this is a safety check
        if not isinstance(test_data, str):
            return (
                False,
                f'Invalid test_data: {test_data}. A string of strptime is required.',
            )

        if self.check_null(app_data):
            return False, f'Invalid app_data: {app_data}. One or more values in app_data is null.'

        app_data = app_data if isinstance(app_data, list) else [app_data]
        bad_data = []
        passed = True
        for data in app_data:
            try:
                datetime.datetime.strptime(data, test_data).astimezone(datetime.UTC)
            except ValueError:
                bad_data.append(data)
                passed = False
        return passed, ','.join(bad_data)

    @staticmethod
    def operator_deep_diff(
        app_data: dict | list | str, test_data: dict | list | str, **kwargs
    ) -> tuple[bool, str]:
        """Compare app data equals tests data.

        Due to some values coming in as StringVariables, we want to ignore type differences
        kwargs['ignore_string_type_changes'] = True
        """
        # quick validate -> pass is both values are null
        if app_data is None and test_data is None:
            return True, ''

        # quick validate -> fail if either value is null
        if test_data is None or app_data is None:
            return False, f'App Data {app_data} does not match Test Data {test_data}'

        def _safe_data(data: dict | list | str) -> dict | list | str:
            """Return the date formatted to be safely validated."""
            # deepdiff doesn't handle ordered dicts properly
            safe_data = data
            if isinstance(data, StringVariable):
                safe_data = str(data)
            elif isinstance(data, OrderedDict):
                safe_data = json.loads(json.dumps(data))
            elif isinstance(data, list):
                safe_data = []
                for ad in data:
                    if isinstance(ad, OrderedDict):
                        safe_data.append(json.loads(json.dumps(ad)))
                    elif isinstance(ad, StringVariable):
                        safe_data.append(str(ad))
                    else:
                        safe_data.append(ad)
            return safe_data

        # update app_data
        safe_app_data = _safe_data(app_data)

        # update test_data
        safe_test_data = _safe_data(test_data)

        # using ignore_string_type_change doesn't appear
        # to work and may not be the best approach
        # https://zepworks.com/deepdiff/current
        # /ignore_types_or_values.html#ignore-string-type-changes

        try:
            diff = DeepDiff(safe_app_data, safe_test_data, **kwargs)
        except KeyError:
            return False, 'Encountered KeyError when running deepdiff'
        except NameError:
            return False, 'Encountered NameError when running deepdiff'

        if diff:
            return False, str(diff)
        return True, ''

    @staticmethod
    def operator_endswith(app_data: str, test_data: str) -> tuple[bool, str]:
        """Compare app data ends with tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        return app_data.endswith(test_data), ''

    def operator_eq(
        self, app_data: dict | list | str, test_data: dict | list | str
    ) -> tuple[bool, str]:
        """Compare app data is equal to tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        results = operator.eq(app_data, test_data)
        return results, self.details(app_data, test_data, 'eq')

    def operator_ge(
        self, app_data: float | str | None, test_data: float | str | None
    ) -> tuple[bool, str]:
        """Compare app data is greater than or equal to tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        if app_data is None:
            return False, f'Invalid app_data: {app_data}. App Data can not be null.'

        if test_data is None:
            return False, f'Invalid test_data: {test_data}. Test Data can not be null.'

        app_data = self._string_to_int_float(app_data)
        test_data = self._string_to_int_float(test_data)
        results = operator.ge(app_data, test_data)  # type: ignore
        details = ''
        if not results:
            details = f'{app_data} {type(app_data)} !(>=) {test_data} {type(test_data)}'
        return results, details

    def operator_gt(
        self, app_data: float | str | None, test_data: float | str | None
    ) -> tuple[bool, str]:
        """Compare app data is greater than tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        if app_data is None:
            return False, f'Invalid app_data: {app_data}. App Data can not be null.'

        if test_data is None:
            return False, f'Invalid test_data: {test_data}. Test Data can not be null.'

        app_data = self._string_to_int_float(app_data)
        test_data = self._string_to_int_float(test_data)
        results = operator.gt(app_data, test_data)  # type: ignore
        details = ''
        if not results:
            details = f'{app_data} {type(app_data)} !(>) {test_data} {type(test_data)}'
        return results, details

    @staticmethod
    def operator_hash_eq(app_data: bytes | str, test_data: str, **kwargs) -> tuple[bool, str]:
        """Compare SHA256 hash of app data against SHA256 hash stored in expected_output."""
        if isinstance(app_data, bytes | bytearray):
            app_data_hash = hashlib.sha256(app_data).hexdigest()
        elif isinstance(app_data, str):
            encoding = kwargs.get('encoding', 'utf-8')
            app_data_hash = hashlib.sha256(app_data.encode(encoding)).hexdigest()
        else:
            return (
                False,
                f'heq only supports Binary and String outputs, but app data was {type(app_data)}',
            )

        if test_data != app_data_hash:
            # handle "null" match
            return False, f'App Data is {app_data_hash} but Test Data is {test_data}'

        return True, ''

    def operator_is_date(self, app_data: list[str] | str, _: None) -> tuple[bool, str]:
        """Check if the app_data is a known date."""
        if app_data is None:
            return False, f'Invalid app_data: {app_data}. One or more values in app_data is null.'

        app_data = app_data if isinstance(app_data, list) else [app_data]
        bad_data = []
        passed = True
        for data in app_data:
            try:
                self.util.any_to_datetime(data)
            except RuntimeError:
                bad_data.append(data)
                passed = False
        return passed, ','.join(bad_data)

    def operator_is_json(self, app_data: list | str, _: None) -> tuple[bool, str]:
        """Check if the app_data is a json."""
        if self.check_null(app_data):
            return False, f'Invalid app_data: {app_data}. One or more values in app_data is null.'

        app_data = app_data if isinstance(app_data, list) else [app_data]
        bad_data = []
        for data in app_data:
            if isinstance(data, str):
                try:
                    data_ = json.loads(data)
                    if not isinstance(data_, list):
                        data_ = [data_]
                    for item in data_:
                        if not isinstance(item, dict):
                            bad_data.append(f'Invalid JSON data provide ({item}).')
                except ValueError:
                    bad_data.append(f'Invalid JSON data provide ({data}).')
            elif isinstance(data, OrderedDict | dict):
                try:
                    data_ = json.dumps(data)
                except ValueError:
                    bad_data.append(f'Invalid JSON data provide ({data}).')
            else:
                bad_data.append(f'Invalid JSON data provide ({data}).')

        if bad_data:
            return False, ','.join(bad_data)
        return True, ','.join(bad_data)

    def operator_is_number(self, app_data: int | list | str, _: None) -> tuple[bool, str]:
        """Check if the app_data is a number."""
        if self.check_null(app_data):
            return False, f'Invalid app_data: {app_data}. One or more values in app_data is null.'

        app_data = app_data if isinstance(app_data, list) else [app_data]
        bad_data = []
        passed = True
        for data in app_data:
            if isinstance(data, str) and isinstance(self._string_to_int_float(data), int | float):
                continue
            if isinstance(data, numbers.Number):
                continue
            bad_data.append(data)
            passed = False
        return passed, ','.join(bad_data)

    def operator_is_url(self, app_data: list[str] | str, _: None) -> tuple:
        """Check if the app_data is a known date."""
        if self.check_null(app_data):
            return False, f'Invalid app_data: {app_data}. One or more values in app_data is null.'

        app_data = app_data if isinstance(app_data, list) else [app_data]
        bad_data = []
        passed = True
        regex = re.compile(
            r'^(?:http|ftp)s?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$',
            re.IGNORECASE,
        )
        for data in app_data:
            try:
                matched = re.match(regex, data)
                if not matched:
                    bad_data.append(data)
                    passed = False
            except RuntimeError:
                bad_data.append(data)
                passed = False
        return passed, ','.join(bad_data)

    def operator_json_eq(
        self, app_data: dict | list | str | None, test_data: dict | list | str | None, **kwargs
    ) -> tuple:
        """Compare app data equals tests data.

        Takes a str, dict, or list value and removed field before passing to deepdiff. Only fields
        at the "root" level can be removed (e.g., "date", not "data.date").
        """
        # quick validate -> pass is both values are null
        if app_data is None and test_data is None:
            return True, ''

        # quick validate -> fail if either value is null
        if test_data is None or app_data is None:
            return False, f'App Data {app_data} does not match Test Data {test_data}'

        try:
            app_data = self._load_json_data(app_data)
        except ValueError:
            return False, f'Invalid JSON data provide ({app_data}).'

        try:
            test_data = self._load_json_data(test_data)
        except ValueError:
            return False, f'Invalid JSON data provide ({test_data}).'

        exclude = kwargs.pop('exclude', [])
        if isinstance(app_data, list) and isinstance(test_data, list):
            app_data = [self.operator_json_eq_exclude(ad, exclude) for ad in app_data]
            test_data = [self.operator_json_eq_exclude(td, exclude) for td in test_data]
        elif isinstance(app_data, dict) and isinstance(test_data, dict):
            app_data = self.operator_json_eq_exclude(app_data, exclude)
            test_data = self.operator_json_eq_exclude(test_data, exclude)

        return self.operator_deep_diff(app_data, test_data, **kwargs)

    def operator_json_eq_exclude(self, data: dict | list, exclude: list) -> dict | list:
        """Remove excluded field from dictionary."""
        for e in exclude:
            try:
                es = e.split('.')
                data = self.remove_excludes(data, es)
            except (AttributeError, KeyError, TypeError):
                self.log.exception(
                    f'step=validate, event=invalid-validation-configuration, exclude={e}'
                )
        return data

    def operator_keyvalue_eq(self, app_data: dict, test_data: dict, **kwargs) -> tuple:
        """Compare app data equals tests data."""
        # remove exclude_key field. usually dynamic data like date fields.
        if kwargs.get('exclude_keys') is not None:
            app_data = {
                k: v for k, v in app_data.items() if k not in kwargs.get('exclude_keys', [])
            }
            test_data = {
                k: v for k, v in test_data.items() if k not in kwargs.get('exclude_keys', [])
            }
            del kwargs['exclude_keys']

        return self.operator_deep_diff(app_data, test_data, **kwargs)

    def operator_le(
        self, app_data: float | str | None, test_data: float | str | None
    ) -> tuple[bool, str]:
        """Compare app data is less than or equal to tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        return self._basic_operator(app_data, test_data, operator.le)

    @staticmethod
    def operator_length_eq(app_data: list | str, test_data: int | list | str):
        """Check length of app_data.

        If data passed in is 2 lists, validates length lists are the same.
        If data passed in is 2 strings, validates length strings are the same.
        If data passed in is 1 list and 1 int, validates length array and int value are the same.
        If data passed in is 1 str and 1 int, validates length str and int value are the same.
        """
        if app_data is None:
            return False, f'Invalid test_data: {app_data}. Value in app_data is null.'
        if test_data is None:
            return False, f'Invalid test_data: {test_data}. Value in test_data is null.'

        if not (
            (isinstance(test_data, str) and isinstance(app_data, str))
            or (isinstance(test_data, list) and isinstance(app_data, list))
            or (isinstance(test_data, int) and isinstance(app_data, list | str))
        ):
            msg = (
                f'Cannot compare App Data Type: {type(app_data)} '
                f'to Test Data Type {type(test_data)}'
            )
            return False, msg
        app_len = len(app_data)
        test_len = test_data if isinstance(test_data, int) else len(test_data)

        results = operator.eq(app_len, test_len)
        return results, f'App Data Length: {app_len} | Test Data Length: {test_len}'

    def operator_lt(self, app_data: int | str, test_data: int | str) -> tuple:
        """Compare app data is less than tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        return self._basic_operator(app_data, test_data, operator.lt)

    def operator_ne(self, app_data: float | str, test_data: float | str) -> tuple:
        """Compare app data is not equal to tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        results = operator.ne(app_data, test_data)
        return results, self.details(app_data, test_data, 'ne')

    def operator_regex_match(self, app_data: list | str, test_data: str):
        """Compare app data matches test regex data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        if self.check_null(test_data):
            return (
                False,
                f'Invalid test_data: {test_data}. One or more values in test_data is null.',
            )
        if self.check_null(app_data):
            return False, f'Invalid app_data: {app_data}. One or more values in app_data is null.'

        if isinstance(app_data, (bytes | dict)):
            return False, 'Invalid app_data, bytes or dict types are not supported.'

        if not isinstance(app_data, list):
            app_data = [app_data]
        bad_data = []
        passed = True
        for data in app_data:
            if re.match(test_data, data) is None:
                bad_data.append(data)
                passed = False

        bad_data = ','.join(bad_data)  # convert bad_data to string for assertion error
        if bad_data:
            bad_data = f'Failed inputs: {bad_data}'
        return passed, bad_data

    @staticmethod
    def operator_skip(_app_data, _test_data):
        """Skip validation and always return True.

        Args:
            app_data (str, list): The data created by the App.
            test_data (str): The data provided in the test case.

        Returns:
            bool: The results of the operator.
        """
        return True, 'skipped'

    @staticmethod
    def operator_startswith(app_data: str, test_data: str) -> tuple:
        """Compare app data starts with tests data.

        Args:
            app_data: The data created by the App.
            test_data: The data provided in the test case.
        """
        return app_data.startswith(test_data), ''

    @abstractmethod
    def remove_excludes(self, dict_1: dict | list, paths: list) -> dict | list:
        """Remove a list of paths from a given dict"""
