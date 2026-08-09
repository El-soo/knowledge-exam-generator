from django.apps import AppConfig
from django.db.backends.signals import connection_created

def configure_sqlite(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=20000;")

class CommonConfig(AppConfig):
    name = "common"
    def ready(self):
        connection_created.connect(configure_sqlite)
