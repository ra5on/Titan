"""Human network names separate from stable internal paths and permission IDs."""
import re
import unicodedata
import uuid

from .core import Error


def display_name(value):
    if not isinstance(value, str):
        raise Error('Einen Namen für die Freigabe angeben.')
    value = unicodedata.normalize('NFC', value.strip())
    if (not value or len(value) > 80 or value.endswith('.') or
            any(unicodedata.category(char).startswith('C') or char in '[]/\\:;|=,+*?<>"%$' for char in value)):
        raise Error('Freigabenamen dürfen bis zu 80 Zeichen, Leerzeichen und Umlaute enthalten. Pfad- und Sonderzeichen wie /, \\, [, ] oder % sind nicht erlaubt.')
    if value.casefold() in {'global', 'homes', 'printers'} or value.casefold().startswith('extern-'):
        raise Error('Dieser Freigabename ist für Systemdienste reserviert.')
    return value


def network_name(share):
    return display_name(share.get('label', share['name']))


def identity(value):
    label = display_name(value)
    if re.fullmatch(r'[a-z][a-z0-9_-]{0,30}', label):
        return label, label
    slug = unicodedata.normalize('NFKD', label).encode('ascii', 'ignore').decode().lower()
    slug = re.sub('[^a-z0-9]+', '-', slug).strip('-')[:20]
    if not slug or not slug[0].isalpha():
        slug = 'daten-' + slug
    return slug[:22] + '-' + uuid.uuid4().hex[:8], label
