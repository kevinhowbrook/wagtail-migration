from wagtailmigration.news.models import NewsPage, NewsIndex

from .base import BasePageImporter


class NewsImporter(BasePageImporter):
    """
    Example use of the BasePageImporter for importing a specific page type
    """

    content_model = NewsPage
    parent_page_model = NewsIndex

    def format_data(self, data):
        """ Overridden to add a body field """
        formatted_data = super().format_data(data)

        # format a rich text field
        body = self.format_rich_text(self.get_value(data, 'body'))
        publication_date = formatted_data['first_published_at']

        formatted_data.update({
            'body': body,
            'publication_date': publication_date,

        })
        return formatted_data
