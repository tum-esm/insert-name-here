import typing

import asyncpg
import jinja2

import app.constants as constants
import app.settings as settings


CONFIGURATION = {
    "dsn": settings.POSTGRESQL_URL,
    "user": settings.POSTGRESQL_IDENTIFIER,
    "password": settings.POSTGRESQL_PASSWORD,
}

templates = jinja2.Environment(
    loader=jinja2.PackageLoader(package_name="app", package_path="queries"),
    autoescape=jinja2.select_autoescape(),
)


def dictify(result: typing.Sequence[asyncpg.Record]) -> list[dict]:
    """Cast a database SELECT result into a list of dictionaries."""
    return [dict(record) for record in result]


class Serial(dict):
    def __getitem__(self, key):
        return f"${list(self.keys()).index(key) + 1}"


def build(
    template: str,
    template_parameters: dict[str, typing.Any],
    query_parameters: dict[str, typing.Any],
) -> tuple[str, list[typing.Any]]:
    """Dynamically build asyncpg query.

    1. Render Jinja2 template with the given template parameters
    2. Translate given named query parameters to unnamed asyncpg query parameters

    """
    query = templates.get_template(template).render(**template_parameters)
    for key in list(query_parameters.keys()):  # copy keys to avoid modifying iterator
        if f"{{{key}}}" not in query:
            query_parameters.pop(key)
    return (
        query.format_map(Serial(**query_parameters)),
        list(query_parameters.values()),
    )


async def initialize(database_client):
    """Create tables, and error out if existing tables don't match the schema."""
    await database_client.execute(
        query=templates.get_template("create_table_configurations.sql").render()
    )
    await database_client.execute(
        query=templates.get_template("create_table_measurements.sql").render()
    )
