"""TcEx Framework Module"""

# standard library
import base64
import binascii
import logging

# third-party
from redis import Redis

# first-party
from tcex_app_testing.app.playbook import Playbook
from tcex_app_testing.render.render import Render

# get logger
_logger = logging.getLogger(__name__.split('.', maxsplit=1)[0])


class StagerKvstore:
    """Stages the Redis Data"""

    def __init__(self, playbook: Playbook, redis_client: Redis):
        """Initialize class properties."""
        self.playbook = playbook
        self.redis_client = redis_client

        # properties
        self.log = _logger

    def from_dict(self, staging_data: dict):
        """Stage redis data from dict"""
        for variable, data in staging_data.items():
            variable_type = self.playbook.get_variable_type(variable)
            self.log.info(f'step=stage, data=from-dict, variable={variable}, value={data}')

            if data is not None:
                if variable_type == 'Binary':
                    data_ = self._decode_binary(data, variable)
                elif variable_type == 'BinaryArray':
                    data_ = [self._decode_binary(d, variable) for d in data]
                else:
                    data_ = data

                self.playbook.create.any(
                    variable,
                    data_,  # type: ignore
                    validate=False,
                    when_requested=False,
                )

    def stage(
        self,
        variable: str,
        data: bytes | dict | str | list[bytes] | list[dict] | list[str],
    ):
        """Stage data in redis"""
        self.playbook.create.any(variable, data, when_requested=False)

    def delete_context(self, context: str):
        """Delete data in redis"""
        keys = self.redis_client.hkeys(context)
        if keys:
            return self.redis_client.hdel(context, *keys)
        return 0

    @staticmethod
    def _decode_binary(binary_data: bytes | None, variable: str) -> bytes | None:
        """Base64 decode binary data."""
        try:
            data = None
            if binary_data is not None:
                data = base64.b64decode(binary_data)
        except binascii.Error as e:
            Render.panel.failure(
                f'The Binary staging data for variable {variable} '
                f'is not properly base64 encoded due to {e}.'
            )
        return data
