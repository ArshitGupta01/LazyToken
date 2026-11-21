"""Semantic checks for the static desktop and phone entry points."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}


class PageSemantics(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.ids = {}
        self.mains = []
        self.navs = []
        self.controls = []
        self.fields = []
        self.label_targets = set()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get("id"):
            self.ids[attrs["id"]] = attrs
        if tag == "main":
            self.mains.append(attrs)
        if tag == "nav":
            self.navs.append(attrs)
        if tag == "label" and attrs.get("for"):
            self.label_targets.add(attrs["for"])
        hidden = attrs.get("aria-hidden") == "true" or any(item[2] for item in self.stack)
        control = None
        if tag in {"a", "button"}:
            control = len(self.controls)
            self.controls.append({"tag": tag, "attrs": attrs, "text": ""})
        if tag == "img" and not hidden and attrs.get("alt"):
            for _, index, _ in self.stack:
                if index is not None:
                    self.controls[index]["text"] += attrs["alt"]
        if tag in {"input", "select", "textarea"} and attrs.get("type") != "hidden":
            self.fields.append((attrs, any(item[0] == "label" for item in self.stack)))
        if tag not in VOID:
            self.stack.append((tag, control, hidden))

    def handle_startendtag(self, tag, attributes):
        self.handle_starttag(tag, attributes)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        if any(item[2] for item in self.stack):
            return
        for _, index, _ in self.stack:
            if index is not None:
                self.controls[index]["text"] += data


class AccessibilityContractTests(unittest.TestCase):
    def parse(self, path):
        page = PageSemantics()
        page.feed((ROOT / path).read_text(encoding="utf-8"))
        return page

    def test_primary_pages_keep_main_landmarks_and_named_controls(self):
        for path in ("index.html", "web/index.html", "web/setup.html", "web/mobile.html"):
            with self.subTest(path=path):
                page = self.parse(path)
                self.assertTrue(page.mains)
                self.assertTrue(all(main.get("role", "main") == "main" for main in page.mains))
                self.assertTrue(all(nav.get("aria-label", "").strip() for nav in page.navs))
                for control in page.controls:
                    name = control["attrs"].get("aria-label") or control["text"]
                    self.assertTrue(name.strip(), (path, control["tag"], control["attrs"]))
                for attrs, wrapped in page.fields:
                    named = (
                        attrs.get("aria-label")
                        or attrs.get("aria-labelledby")
                        or attrs.get("id") in page.label_targets
                        or wrapped
                    )
                    self.assertTrue(named, (path, attrs))

    def test_phone_navigation_targets_focusable_panel_headings(self):
        page = self.parse("web/mobile.html")
        for panel, heading in (
            ("prompts", "pocket-title"),
            ("benchmarks", "benchmarks-title"),
            ("help", "help-title"),
        ):
            with self.subTest(panel=panel):
                self.assertEqual(page.ids[f"{panel}-panel"].get("aria-labelledby"), heading)
                self.assertEqual(page.ids[heading].get("tabindex"), "-1")
                buttons = [
                    control
                    for control in page.controls
                    if control["attrs"].get("data-panel") == panel
                ]
                self.assertEqual(len(buttons), 1)
                self.assertEqual(buttons[0]["tag"], "button")


if __name__ == "__main__":
    unittest.main()
