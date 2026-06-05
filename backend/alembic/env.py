"""Alembic environment — reads DATABASE_URL_SYNC from .env."""

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Pull sync URL from env (asyncpg URL won't work with Alembic's sync engine)
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL_SYNC"])

# Import models so Alembic can see them for autogenerate (not used here, but good practice)
from app.models import Base  # noqa: E402
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
