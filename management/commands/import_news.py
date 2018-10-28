from .base import BaseCommand

from ...importers.news import NewsImporter


class Command(BaseCommand):
    """
    Example import management command to import news
    """
    importer = NewsImporter
