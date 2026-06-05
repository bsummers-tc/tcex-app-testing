"""TcEx Framework Module"""

# standard library
import json
import os
import re
import uuid
from functools import partial
from pathlib import Path

# third-party
import requests
import responses
from pydantic import BaseModel
from responses import matchers

# first-party
from tcex_app_testing.render.render import Render


class StageRequestMethodModel(BaseModel):
    """Model Definition"""

    url: str
    output_file: str
    params: None | dict = {}
    headers: None | dict = {}
    body: None | str | dict = None
    status_code: None | int = 200

    def info(self):
        """Display the request."""
        return (
            f'URL: {self.url} output_file: {self.output_file}, status_code: {self.status_code} '
            f'params: {self.params}'
        )


def response_callback(_, staged_request: StageRequestMethodModel, output_path: Path):
    """Return the staged response."""
    responses.stop()
    output_file = output_path / Path(staged_request.output_file)
    if output_file.exists():
        with output_file.open(encoding='utf-8') as f:
            data = f.read()
        returned_data = staged_request.status_code, staged_request.headers, data
    else:
        Render.panel.error(f'Output file does not exist: {output_file}')
        ex_msg = f'Output file does not exist: {output_file}'
        raise RuntimeError(ex_msg)
    responses.start()
    return returned_data


def generate_file_name(request, response) -> str:
    """Generate a file name for the request."""
    content_type = response.headers.get('content-type', '').split(';')

    file_extension = 'unknown' if not content_type else content_type[0].split('/')[-1]

    # Convert the dictionary to a JSON string
    json_data = json.dumps(request.params, sort_keys=True)
    if request.body:
        json_data += str(request.body)

    # Define a namespace UUID (e.g., UUID for DNS namespace)
    namespace_uuid = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

    # Create a UUIDv5 by hashing the namespace and JSON data
    uuid5 = uuid.uuid5(namespace_uuid, json_data)
    return (
        f'{request.method.lower()}-'
        f'{request.url.split("?")[0].split("/")[-1]}-'
        f'{uuid5}.'
        f'{file_extension}'
    )


def record_all_callback(request, recorded_data: dict, output_path: Path):
    """Record all requests."""
    responses.stop()
    request_args = {
        'method': request.method,
        'url': request.url,
        'headers': request.headers,
        'data': request.body,
    }
    request_args = {k: v for k, v in request_args.items() if v}
    response = requests.request(**request_args)
    if request.url.startswith(os.getenv('VAULT_URL', '')) or request.method == 'OPTIONS':
        responses.start()
        return response.status_code, {}, response.text
    file_name = generate_file_name(request, response)
    with (output_path / file_name).open(mode='w', encoding='utf-8') as f:
        content = response.text
        if file_name.endswith('.json'):
            content = json.dumps(response.json())
        f.write(content)

    data = {
        'url': request.url,
        'params': request.params,
        'status_code': response.status_code,
        'output_file': file_name,
    }
    recorded_data.setdefault(request.method.lower(), []).append(data)
    responses.start()
    return response.status_code, {}, response.text


class StagerRequest:
    """Stages the Redis Data"""

    @property
    def input_path(self):
        """Return the input path"""
        path_ = self.base_path / Path('input')
        path_.mkdir(parents=True, exist_ok=True)
        return path_

    @property
    def output_path(self):
        """Return the output path"""
        path_ = self.base_path / Path('output')
        path_.mkdir(parents=True, exist_ok=True)
        return path_

    @property
    def base_path(self):
        """Return the base path"""
        test_path = Path(os.getenv('PYTEST_CURRENT_TEST')).parent  # type: ignore
        return test_path / Path('staged_requests')

    def record_all(self, recorded_data) -> None:
        """Record all requests."""
        methods = [
            responses.GET,
            responses.POST,
            responses.PUT,
            responses.DELETE,
            responses.OPTIONS,
        ]
        for method in methods:
            responses.add_callback(
                method,
                re.compile(r'.*'),
                callback=partial(
                    record_all_callback, recorded_data=recorded_data, output_path=self.output_path
                ),
            )

    def stage(self, request_data) -> None:
        """Stage redis data from dict"""
        for key, requests_ in request_data.items():
            key_ = key.upper()
            for request in requests_:
                request_ = StageRequestMethodModel(**request)

                match = []
                match_querystring = False
                if request_.params is not None:
                    match = [matchers.query_param_matcher(request_.params)]
                    match_querystring = True

                callback = partial(
                    response_callback,
                    staged_request=request_,
                    output_path=self.output_path,
                )

                responses.add_callback(
                    getattr(responses, key_),
                    url=request_.url,
                    callback=callback,
                    match_querystring=match_querystring,
                )
                responses.add(
                    method=key_,
                    url=request_.url,
                    status=request_.status_code,
                    match=match,
                )
