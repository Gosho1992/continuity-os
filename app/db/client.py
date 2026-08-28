"""ClickHouse connection for ContinuityOS."""

import os
from dotenv import load_dotenv
import clickhouse_connect

load_dotenv()


def get_client():
    """Return a connected ClickHouse client."""
    return clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", 8443)),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ["CLICKHOUSE_PASSWORD"],
        database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
        secure=True,
    )