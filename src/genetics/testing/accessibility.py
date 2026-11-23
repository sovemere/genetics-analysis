"""An accessibility audit of the dashboard's markup (roadmap M14.7).

A library, not a test file, as :mod:`genetics.testing.parity` is: the suites that build the
only saved runs with a drawn ancestry scatter, HLA calls or guideline cards can audit their
pages with the same rules ``tests/web/test_accessibility.py`` applies to the rest.

What :func:`audit` checks is listed in its docstring. It reads markup with the standard
library's parser and computes nothing about colour; :func:`contrast` is WCAG's ratio, for
the stylesheet's tokens. No message here quotes page text beyond an id, a tag or a control's
``name``, so a failure on a page that states a genotype does not repeat it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from itertools import pairwise

__all__ = ["Element", "audit", "by_id", "contrast", "name_of", "parse"]


def _luminance(colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


@dataclass
class Element:
    tag: str
    attrs: dict[str, str]
    parent: Element | None
    children: list[Element | str] = field(default_factory=list)

    def get(self, name: str) -> str | None:
        return self.attrs.get(name)

    def ancestors(self) -> Iterator[Element]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def walk(self) -> Iterator[Element]:
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.walk()

    def text(self, *, skip_hidden: bool = True) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif (
                child.tag in {"script", "style"}
                or (child.tag, self.tag) == ("title", "head")
                or (skip_hidden and child.get("aria-hidden") == "true")
            ):
                continue
            else:
                parts.append(child.text(skip_hidden=skip_hidden))
        return " ".join(" ".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {}, None)
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, {k: v or "" for k, v in attrs}, self.current)
        self.current.children.append(element)
        if tag not in VOID:
            self.current = element

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.current.children.append(Element(tag, {k: v or "" for k, v in attrs}, self.current))

    def handle_endtag(self, tag: str) -> None:
        node: Element | None = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def parse(html: str) -> Element:
    tree = _Tree()
    tree.feed(html)
    tree.close()
    return tree.root


def by_id(root: Element) -> dict[str, Element]:
    return {e.attrs["id"]: e for e in root.walk() if "id" in e.attrs}


def name_of(element: Element, ids: dict[str, Element]) -> str:
    """The accessible name, as far as this markup needs: labelledby, label, then content."""
    if element.get("aria-labelledby"):
        return " ".join(ids[ref].text() for ref in element.attrs["aria-labelledby"].split())
    if element.get("aria-label"):
        return element.attrs["aria-label"]
    return element.text()


LANDMARK_ROLES = {
    "nav": "navigation",
    "main": "main",
    "header": "banner",
    "footer": "contentinfo",
    "aside": "complementary",
}
SECTIONING = {"article", "aside", "main", "nav", "section"}
FOCUSABLE = {"a", "button", "input", "select", "textarea", "summary"}


def _focusable(element: Element) -> bool:
    if element.tag == "input" and element.get("type") == "hidden":
        return False
    if element.tag == "a" and "href" not in element.attrs:
        return False
    tabindex = element.get("tabindex")
    if tabindex is not None:
        return int(tabindex) >= 0
    return element.tag in FOCUSABLE


def audit(html: str, *, page: bool = True) -> list[str]:
    """Every problem this audit knows how to see on one page, or on a fragment (``page``
    false): an empty list is a pass.

    Everywhere: ids unique; every ``aria-labelledby``, ``aria-describedby`` and label
    ``for`` points at an id; no positive ``tabindex``; nothing focusable inside an
    ``role="img"`` or ``aria-hidden`` subtree; every link and button named; every visible
    control labelled; every ``role="img"`` named; every table captioned (M15.5,
    finishing M14.7). On a page, also: ``lang`` and a title;
    one ``main`` with one ``h1`` and no skipped heading level in it; and landmarks of one
    role told apart by name when there is more than one.
    """
    root = parse(html)
    elements = list(root.walk())
    ids = by_id(root)
    problems: list[str] = []

    seen: set[str] = set()
    for element in elements:
        if "id" in element.attrs:
            if element.attrs["id"] in seen:
                problems.append(f"duplicate id {element.attrs['id']}")
            seen.add(element.attrs["id"])
        for attribute in ("aria-labelledby", "aria-describedby"):
            for ref in (element.get(attribute) or "").split():
                if ref not in ids:
                    problems.append(f"{attribute} points at no id: {ref}")
        if element.tag == "label" and element.get("for") and element.attrs["for"] not in ids:
            problems.append(f"label for no id: {element.attrs['for']}")

        tabindex = element.get("tabindex")
        if tabindex is not None and int(tabindex) > 0:
            problems.append(f"positive tabindex on {element.tag}")

        if _focusable(element):
            for ancestor in element.ancestors():
                if ancestor.get("role") == "img" or ancestor.get("aria-hidden") == "true":
                    problems.append(f"focusable {element.tag} inside a hidden or image subtree")
            if element.tag in {"a", "button"} and not name_of(element, ids):
                problems.append(f"{element.tag} with no name")

        if element.tag in {"input", "select", "textarea"} and element.get("type") != "hidden":
            labelled = (
                element.get("aria-label")
                or element.get("aria-labelledby")
                or any(a.tag == "label" for a in element.ancestors())
                or any(e.tag == "label" and e.get("for") == element.get("id") for e in elements)
            )
            if not labelled:
                problems.append(f"unlabelled {element.tag} {element.get('name')}")

        if element.get("role") == "img" and not name_of(element, ids):
            problems.append(f"role=img with no name on {element.tag}")

        if element.tag == "table" and not any(
            isinstance(c, Element) and c.tag == "caption" and c.text() for c in element.children
        ):
            problems.append("table with no caption")

    if page:
        html_element = next(e for e in elements if e.tag == "html")
        if not html_element.get("lang"):
            problems.append("no lang on html")
        title = next((e for e in elements if e.tag == "title"), None)
        if title is None or not title.text():
            problems.append("no title")

        main = [e for e in elements if e.tag == "main"]
        if len(main) != 1:
            problems.append(f"{len(main)} main elements")
        else:
            levels = [int(e.tag[1]) for e in main[0].walk() if re.fullmatch(r"h[1-6]", e.tag)]
            if levels.count(1) != 1:
                problems.append(f"{levels.count(1)} h1 in main")
            for before, after in pairwise(levels):
                if after > before + 1:
                    problems.append(f"heading skips from h{before} to h{after}")

        landmarks: dict[str, list[str]] = {}
        for element in elements:
            role = element.get("role") or LANDMARK_ROLES.get(element.tag)
            if element.tag in {"header", "footer"} and any(
                a.tag in SECTIONING for a in element.ancestors()
            ):
                continue  # a card's own header is not the page's banner
            if role in {
                "navigation",
                "search",
                "main",
                "banner",
                "contentinfo",
                "region",
                "complementary",
            }:
                named = element.get("aria-label") or element.get("aria-labelledby")
                landmarks.setdefault(role, []).append(name_of(element, ids) if named else "")
        for role, names in landmarks.items():
            if len(names) > 1 and (len(set(names)) != len(names) or "" in names):
                problems.append(f"{len(names)} {role} landmarks not told apart by name")
    return problems
