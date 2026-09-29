"""Disposable text URL fixture for portable delivery qualification."""
import re
import unicodedata


def _transliterate(text):
    text = text.replace('ß', 'ss').replace('ẞ', 'ss')
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', _transliterate(text).lower()).strip('-')


def truncate_slug(text, max_length):
    if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length <= 0:
        raise ValueError('max_length must be a positive integer')
    truncated = slugify(text)[:max_length]
    if truncated.endswith('-'):
        truncated = truncated[:-1]
    return truncated
