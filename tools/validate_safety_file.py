#!/usr/bin/env python3
"""Validate a JSON document against a JSON Schema, using the standard library only.

It implements exactly the keywords that the draft Cognic safety-file schema
uses: $ref (local "#/..." pointers), type, const, enum, properties,
required, additionalProperties, items, minItems, maxItems, uniqueItems,
contains, pattern, minLength, maxLength, minimum, maximum, minProperties,
maxProperties, allOf, anyOf, not and if/then/else. Annotation keywords
($schema, $id, title, description, examples, $defs, $comment, default) are
ignored. Any other keyword makes validation fail with "unsupported
keyword", so a schema feature this checker does not understand can never
pass silently.

It is not a general JSON Schema 2020-12 implementation (no remote
references, $dynamicRef, unevaluated*, format or vocabularies). The draft
schema itself is not part of this public repository; pass its path.

Usage:
    python3 tools/validate_safety_file.py --schema PATH [--instance cognic-safety.json]
"""

import argparse
import json
import re
import sys

ANNOTATIONS = {"$schema", "$id", "title", "description", "examples", "$defs", "$comment", "default"}
SUPPORTED = {
    "$ref", "type", "const", "enum", "properties", "required", "additionalProperties", "items",
    "minItems", "maxItems", "uniqueItems", "contains", "pattern", "minLength", "maxLength",
    "minimum", "maximum", "minProperties", "maxProperties", "allOf", "anyOf", "not", "if", "then", "else",
}


def _json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return set(a) == set(b) and all(_json_equal(a[k], b[k]) for k in a)
    return a == b


def _is_type(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        if isinstance(value, bool):
            return False
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    raise ValueError("unknown type {!r}".format(name))


class Validator(object):
    def __init__(self, schema):
        self.root = schema

    def _resolve(self, ref):
        if not ref.startswith("#"):
            raise ValueError("only local references are supported: {}".format(ref))
        node = self.root
        for part in ref[1:].split("/")[1:]:
            part = part.replace("~1", "/").replace("~0", "~")
            node = node[int(part)] if isinstance(node, list) else node[part]
        return node

    def errors(self, instance, schema=None, path=""):
        found = []
        self._validate(instance, self.root if schema is None else schema, path or "/", found)
        return found

    def _ok(self, instance, schema, path):
        scratch = []
        self._validate(instance, schema, path, scratch)
        return not scratch

    def _validate(self, value, schema, path, out):
        if schema is True:
            return
        if schema is False:
            out.append((path, "no value is allowed here"))
            return
        unknown = sorted(set(schema) - SUPPORTED - ANNOTATIONS)
        if unknown:
            out.append((path, "unsupported keyword(s) in schema: {}".format(", ".join(unknown))))
            return
        if "$ref" in schema:
            self._validate(value, self._resolve(schema["$ref"]), path, out)
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, t) for t in types):
                out.append((path, "expected type {}, got {!r}".format("/".join(types), value)))
                return
        if "const" in schema and not _json_equal(value, schema["const"]):
            out.append((path, "must equal {!r}".format(schema["const"])))
        if "enum" in schema and not any(_json_equal(value, option) for option in schema["enum"]):
            out.append((path, "{!r} is not one of {!r}".format(value, schema["enum"])))
        for sub in schema.get("allOf", []):
            self._validate(value, sub, path, out)
        if "anyOf" in schema and not any(self._ok(value, sub, path) for sub in schema["anyOf"]):
            out.append((path, "matches none of the anyOf alternatives"))
        if "not" in schema and self._ok(value, schema["not"], path):
            out.append((path, "must not match the 'not' schema"))
        if "if" in schema:
            branch = "then" if self._ok(value, schema["if"], path) else "else"
            if branch in schema:
                self._validate(value, schema[branch], path, out)

        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                out.append((path, "shorter than {}".format(schema["minLength"])))
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                out.append((path, "longer than {}".format(schema["maxLength"])))
            if "pattern" in schema and not re.search(schema["pattern"], value):
                out.append((path, "{!r} does not match {}".format(value, schema["pattern"])))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                out.append((path, "below the minimum {}".format(schema["minimum"])))
            if "maximum" in schema and value > schema["maximum"]:
                out.append((path, "above the maximum {}".format(schema["maximum"])))
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                out.append((path, "fewer than {} items".format(schema["minItems"])))
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                out.append((path, "more than {} items".format(schema["maxItems"])))
            if schema.get("uniqueItems"):
                for i in range(len(value)):
                    for j in range(i + 1, len(value)):
                        if _json_equal(value[i], value[j]):
                            out.append((path, "items {} and {} are equal".format(i, j)))
            if "items" in schema:
                for i, item in enumerate(value):
                    self._validate(item, schema["items"], "{}/{}".format(path.rstrip("/"), i), out)
            if "contains" in schema and not any(self._ok(item, schema["contains"], path) for item in value):
                out.append((path, "no item matches 'contains'"))
        if isinstance(value, dict):
            if "minProperties" in schema and len(value) < schema["minProperties"]:
                out.append((path, "fewer than {} properties".format(schema["minProperties"])))
            if "maxProperties" in schema and len(value) > schema["maxProperties"]:
                out.append((path, "more than {} properties".format(schema["maxProperties"])))
            for name in schema.get("required", []):
                if name not in value:
                    out.append((path, "missing required property {!r}".format(name)))
            properties = schema.get("properties", {})
            for name, item in value.items():
                child = "{}/{}".format(path.rstrip("/"), name)
                if name in properties:
                    self._validate(item, properties[name], child, out)
                elif "additionalProperties" in schema:
                    extra = schema["additionalProperties"]
                    if extra is False:
                        out.append((child, "property not allowed"))
                    elif isinstance(extra, dict):
                        self._validate(item, extra, child, out)


def load_json(path):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key {!r} in {}".format(key, path))
            result[key] = value
        return result
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=no_duplicates)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--schema", required=True)
    parser.add_argument("--instance", default="cognic-safety.json")
    args = parser.parse_args(argv)
    found = Validator(load_json(args.schema)).errors(load_json(args.instance))
    if found:
        for path, message in found:
            print("{}: {}".format(path, message))
        print("INVALID: {} error(s)".format(len(found)))
        return 1
    print("valid: {} against {}".format(args.instance, args.schema))
    return 0


if __name__ == "__main__":
    sys.exit(main())
