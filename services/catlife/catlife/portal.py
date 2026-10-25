"""ASGI entry point for the public portal: `python -m catlife.serve`."""

from catlife import config
from catlife.web import create_app

app = create_app(config.store, config.PUBLIC_URL)
