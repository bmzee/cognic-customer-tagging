"""The standard-library schema validator in tools/, checked with small inline schemas."""

import os
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "tools"))
from validate_safety_file import Validator  # noqa: E402

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "kind", "items"],
    "properties": {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,7}$"},
        "kind": {"enum": ["read", "write"]},
        "flag": {"const": True},
        "count": {"type": "integer", "minimum": 0, "maximum": 3},
        "items": {"type": "array", "items": {"$ref": "#/$defs/item"}, "minItems": 1, "uniqueItems": True,
                  "contains": {"const": "a"}},
        "empty": {"type": "array", "maxItems": 0},
    },
    "allOf": [{"if": {"properties": {"kind": {"const": "write"}}},
               "then": {"required": ["flag"]}}],
    "$defs": {"item": {"type": "string", "maxLength": 2}},
}


class ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.validator = Validator(SCHEMA)

    def errors(self, doc):
        return self.validator.errors(doc)

    def test_valid_document(self):
        self.assertEqual(self.errors({"id": "ok-1", "kind": "read", "items": ["a", "b"], "count": 3, "empty": []}), [])

    def test_each_keyword_rejects(self):
        base = {"id": "ok", "kind": "read", "items": ["a"]}
        cases = [
            (dict(base, extra=1), "property not allowed"),
            ({"id": "ok", "kind": "read"}, "missing required"),
            (dict(base, id="Bad"), "does not match"),
            (dict(base, kind="delete"), "is not one of"),
            (dict(base, count=True), "expected type integer"),
            (dict(base, count=4), "above the maximum"),
            (dict(base, count=-1), "below the minimum"),
            (dict(base, items=[]), "fewer than 1"),
            (dict(base, items=["a", "a"]), "are equal"),
            (dict(base, items=["b"]), "contains"),
            (dict(base, items=["a", "abc"]), "longer than 2"),
            (dict(base, empty=[1]), "more than 0"),
            (dict(base, kind="write"), "missing required property 'flag'"),
            (dict(base, kind="write", flag=1), "must equal True"),
        ]
        for doc, message in cases:
            with self.subTest(message=message):
                found = self.errors(doc)
                self.assertTrue(found, doc)
                self.assertTrue(any(message in m for _, m in found), found)

    def test_unsupported_keyword_never_passes_silently(self):
        validator = Validator({"type": "string", "format": "email"})
        self.assertIn("unsupported keyword", validator.errors("x")[0][1])

    def test_integer_and_bool_are_distinct(self):
        self.assertTrue(Validator({"const": 1}).errors(True))
        self.assertEqual(Validator({"type": "integer"}).errors(2.0), [])


if __name__ == "__main__":
    unittest.main()
