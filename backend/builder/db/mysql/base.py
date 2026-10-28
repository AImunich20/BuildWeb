"""MySQL/MariaDB backend that runs on PyMySQL (pure Python, nothing to compile) and accepts the
MariaDB 10.4 that ships with XAMPP 8.x, which Django 5.2 would otherwise refuse (it wants 10.5+)."""
import pymysql

pymysql.install_as_MySQLdb()

from django.db.backends.mysql import base, features  # noqa: E402


class DatabaseFeatures(features.DatabaseFeatures):
    @property
    def minimum_database_version(self):
        return (10, 4) if self.connection.mysql_is_mariadb else (5, 7)


class DatabaseWrapper(base.DatabaseWrapper):
    features_class = DatabaseFeatures
