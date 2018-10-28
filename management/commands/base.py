import json

from django.core.management.base import BaseCommand as DjangoBaseCommand


class BaseCommand(DjangoBaseCommand):
    """
    Base class for importing from a file into Wagtail using importer classes
    and a JSON source data file.
    """
    importer = None

    def add_arguments(self, parser):
        parser.add_argument(
            'parent_page_id',
            help='The ID of the page to import the files under'
        )
        parser.add_argument('source', help='Migration source JSON file')

    def handle(self, *args, **options):
        """
        Run the import.
        """
        data = self._get_source_data_from_file(options['source'])
        parent_page = self.importer.parent_page_model.objects.get(
            id=options['parent_page_id']
        )
        importer = self.importer(data, parent_page)
        importer.process()

    def _get_source_data_from_file(self, source):
        with open(source, 'rb') as f:
            data = f.read()
        return json.loads(data)
