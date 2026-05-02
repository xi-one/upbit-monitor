import psycopg2

from app.common.config import DbConfig


def create_connection(db_config: DbConfig):
    return psycopg2.connect(
        host=db_config.host,
        database=db_config.database,
        user=db_config.user,
        password=db_config.password,
        port=db_config.port,
    )
