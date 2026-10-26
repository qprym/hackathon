"""Bounded editorial focus shared by ingestion, feed ranking and evaluation."""
import re


def source_focus(title, sources):
    def field(source, name, default=''):
        return source.get(name, default) if isinstance(source, dict) else getattr(source, name, default)
    best = max(sources, key=lambda s: len(field(s, 'content')), default=None)
    content = field(best, 'content') if best is not None else ''
    # Later paragraphs often recount unrelated previous news. They remain available
    # as evidence, but cannot define the primary subject of a personalised card.
    lead = re.split(r'\n\s*\n', content.strip())[0][:700]
    return title + ('\n' + lead if lead else '')


def match(pattern, text):
    return re.search(pattern, text.casefold().replace('ё', 'е')) is not None
