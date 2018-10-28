import os
from datetime import datetime
from html import unescape
from io import BytesIO
from urllib import parse

import requests
from bs4 import BeautifulSoup
from PIL import Image

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify

from wagtail.contrib.redirects.models import Redirect
from wagtail.images import get_image_model

WagtailImage = get_image_model()


class PageTypeException(TypeError):
    pass


class SourceDataException(TypeError):
    pass


class BaseImporter(object):
    """
    Base class containing utilities for creating content-specific importers.

    Subclass to create base classes for content-specific imports, e.g.
    BasePageImporter for pages.

    Subclasses will mainly override 'format_page_data()' to map the required
    data from the source file to the destination content fields. To customise
    the creation of the object override 'create_content_item()'.

    Class attributes:
        content_model: the class of the content to be imported.
        timezone: the timezone to use for formatting dates

    Instance attributes:
        source_data: the JSON source data.
        import_count: running total of imported items.

    """
    content_model = None
    timezone = timezone.utc

    def __init__(self, source_data):
        if type(source_data) is not list:
            raise SourceDataException(
                f'Source data is not a list, is {source_data.__class__}'
            )
        self.source_data = source_data
        self.import_count = 0

    def format_data(self, data):
        """
        Format the basic fields for the content. Extend in child classes for
        more fields.
        """

        # the id used in the source data, used for checking whether the
        # content has already been imported. Amend key as required.
        legacy_id = self.get_value(data, 'nid')

        # most content has a title
        title = self.clean_text(self.get_value(data, 'title'), 255)

        return {
            'legacy_id': legacy_id,
            'title': title,
        }

    def process(self):
        """
        Call from external code to run the import with the supplied source data
        """
        for data in self.source_data:
            if self.content_model.objects.filter(legacy_id=data['nid']).exists():
                print(f"{data['legacy_id']} already exists")
                continue

            formatted_data = self.format_data(data)

            try:
                item = self.create_content_item(formatted_data)
                print(f'Created {item.title}')
            except ValidationError as e:
                msg = f"Could not create {formatted_data['title']}: {e}"
                print(msg)

    def create_content_item(self, data):
        """ Create the content item """
        item = self.content_model(**data)
        item.save()
        return item

    def get_value(self, data, value):
        """
        Get the value from the source data. Override as required to customise
        for source data format.
        """
        return data[value]

    def clean_text(self, value, length=None):
        """ Clean a char or text field, trimming to length if provided """
        value = unescape(strip_tags(value).strip())
        if length is not None:
            return value[:int(length)]
        return value

    def get_date(self, data, date_field):
        return self._format_date(self.get_value(data, date_field))

    def _format_date(self, date):
        """ Format the supplied date for Django datetime field """
        return timezone.make_aware(
            datetime.strptime(date, "%Y-%m-%d %H:%M:%S"), self.timezone
        )

    def get_wagtail_image(self, url):
        """
        Looks for an existing image with the same name, otherwise downloads
        and saves the image.
        """
        filename = self._filename_from_url(url)

        # see if an image with the same name exists
        try:
            return WagtailImage.objects.get(title=filename)
        except WagtailImage.DoesNotExist:
            pass

        # otherwise download
        print(f"Downloading {url}")
        response = requests.get(url)

        if response.status_code != 200:
            print(f"Error {response.status_code} downloading: {url}")
            return None

        # check its a valid image
        pil_image = Image.open(BytesIO(response.content))
        pil_image.verify()

        # save and return
        return WagtailImage.objects.create(
            title=filename,
            file=SimpleUploadedFile(filename, response.content)
        )

    def _filename_from_url(self, url):
        url_parsed = parse.urlparse(url)
        return os.path.split(url_parsed.path)[1]


class BaseContentImporter(BaseImporter):
    """
    Base class for importing non-page content.
    """

    def format_data(self, data):
        """
        Format the basic fields. Extend in child classes for more fields.
        Amend keys as required.
        """
        formatted_data = super().format_data(data)

        # Set the slug, remove as appropriate
        # if the content type has a slug.
        slug = self.get_slug_from_data(data, 'slug')
        # or use title
        slug = self.get_slug_from_title(data['title'])

        formatted_data.update({
            'slug': slug
        })
        return formatted_data

    def get_slug_from_data(self, data, slug_field):
        return self._find_available_slug(self.get_value(data, slug_field))

    def get_slug_from_title(self, title):
        return self._find_available_slug(slugify(title))

    def _find_available_slug(self, requested_slug):
        """ Find a slug for non-page content. """
        slug = requested_slug
        number = 1
        while self.__class__.objects.filter(slug=slug).exists():
            slug = requested_slug + '-' + str(number)
            number += 1
        return slug


class BasePageImporter(BaseImporter):
    """
    Base class for creating page-specific importers.

    Class attributes:
        page_model: the class of the page to be imported.
        parent_page_model: the class of the parent page to import under.

    Instance attributes:
        parent_page: the parent page to import under.
        source_data: the JSON source data.
        import_count: running total of imported items.

    Subclasses will mainly override 'format_page_data()' to map the required
    data
    """
    parent_page_model = None

    def __init__(self, data, parent_page):
        super().__init__(data)
        if type(parent_page) is not self.parent_page_model:
            raise PageTypeException(f'Parent page is {parent_page.__class__}, should be {self.parent_page_model}')
        self.parent_page = parent_page

    def format_data(self, data):
        """
        Format the basic page fields. Extend in child classes for more fields.
        Amend keys as required.
        """
        formatted_data = super().format_data(data)

        # the date that the content was created
        first_published_at = self.get_date(data, 'created')

        # keep the old URL for reference and creating redirects
        legacy_url = self.get_value(data, 'url')

        # Get the slug, delete as appropriate:
        # if the source data has a slug field
        slug = self.get_slug_from_data(data, 'slug')
        # or if no slug field but has legacy URL
        slug = self.get_slug_from_url(legacy_url)
        # else use the title
        slug = self.get_slug_from_title(data['title'])

        # gets an image from a URL
        image = self.get_wagtail_image(self.get_value(data, 'image'))

        formatted_data.update({
            'first_published_at': first_published_at,
            'slug': slug,
            'legacy_url': legacy_url,
            'image': image,
        })
        return formatted_data

    def create_content_item(self, data):
        """ Create a page content item """
        page = self.content_model(**data)

        # Add page to parent
        self.parent_page.add_child(instance=page)

        # Save a revision
        revision = page.save_revision()
        revision.publish()

        # create a redirect
        self.create_redirect(page)

        return page

    def get_slug_from_data(self, data, slug_field):
        return self._find_available_page_slug(
            self.get_value(data, slug_field), self.parent_page
        )

    def get_slug_from_url(self, url):
        """ Return the slug from the supplied URL """
        parsed_url = parse.urlparse(url)
        path = parsed_url.path
        path_components = [
            component for component in path.split('/') if component
        ]
        requested_slug = path_components[-1]
        requested_slug = slugify(parse.unquote(path_components[-1]))
        return self._find_available_page_slug(requested_slug, self.parent_page)

    def get_slug_from_title(self, title):
        return self._find_available_page_slug(slugify(title), self.parent_page)

    def _find_available_page_slug(self, requested_slug, parent_page):
        """ Find a slug for page content type. """
        existing_slugs = set(parent_page.get_children().filter(
            slug__startswith=requested_slug).values_list('slug', flat=True))
        slug = requested_slug
        number = 1

        while slug in existing_slugs:
            slug = requested_slug + '-' + str(number)
            number += 1

        return slug

    def create_redirect(self, page):
        Redirect.objects.create(
            old_path=page.legacy_url,
            site=page.get_site(),
            redirect_page=page
        )

    def format_rich_text(self, content):
        """
        Add any code to format rich text data. This example calls a helper
        method to convert image tags into Draftail embed tags.
        """
        content = self._update_images(content)
        return content

    def _update_images(self, content):
        """ Convert the images in img elements into Wagtail embed images. """
        html = BeautifulSoup(content, "html.parser")
        for image in html.find_all('img'):
            try:
                url = image['src']
            except KeyError as e:
                # no url to download from
                continue

            wagtail_image = self.get_wagtail_image(image, url)

            if wagtail_image is not None:
                embed = self._image_to_embed(wagtail_image)
                image.replace_with(embed)

        return str(html)

    def _image_to_embed(self, image):
        soup = BeautifulSoup(features='xml')
        embed = soup.new_tag('embed')
        embed['alt'] = image.title
        embed['caption'] = image.title
        embed['embedtype'] = 'image'
        embed['format'] = 'fullwidth'
        embed['id'] = image.id
        return embed
