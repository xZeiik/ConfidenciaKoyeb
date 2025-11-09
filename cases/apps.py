from django.apps import AppConfig


class CasesConfig(AppConfig):
    name = "cases"

    def ready(self):
        from . import signals  