"""Disposable text URL fixture for portable delivery qualification."""
import re


def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
