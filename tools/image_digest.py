#!/usr/bin/env python3
"""Read an image's manifest digest from an OCI archive and compare it with
the safety file.

python3 tools/image_digest.py IMAGE.tar [IMAGE2.tar] [--check cognic.plugin.json]

Prints the manifest digest of each OCI archive (the digest a registry would
serve the image under). With two archives, fails unless they are equal: the
image must be reproducible from the repository. With --check, fails if the
safety file pins a real digest that differs; a clearly fake placeholder
(all zeros) only gives a warning, because no image has been published yet.
"""

import json
import sys
import tarfile

PLACEHOLDER = "sha256:" + "0" * 64


def manifest_digest(path):
    with tarfile.open(path) as archive:
        index = json.load(archive.extractfile("index.json"))
    manifests = index.get("manifests", [])
    if len(manifests) != 1:
        raise SystemExit("{}: expected one manifest, found {}".format(path, len(manifests)))
    return manifests[0]["digest"]


def _blob(archive, digest):
    return json.load(archive.extractfile("blobs/sha256/" + digest.split(":", 1)[1]))


def explain_difference(first, second):
    """Print which part of the image differs between two archives."""
    parts = []
    for path in (first, second):
        with tarfile.open(path) as archive:
            index = json.load(archive.extractfile("index.json"))
            manifest = _blob(archive, index["manifests"][0]["digest"])
            config = _blob(archive, manifest["config"]["digest"])
            parts.append((manifest, config))
    (m1, c1), (m2, c2) = parts
    for i, (l1, l2) in enumerate(zip(m1["layers"], m2["layers"])):
        if l1["digest"] != l2["digest"]:
            print("  layer {} differs: {} vs {}".format(i, l1["digest"], l2["digest"]))
    for key in sorted(set(c1) | set(c2)):
        if key not in ("rootfs",) and c1.get(key) != c2.get(key):
            print("  config {} differs: {} vs {}".format(key, json.dumps(c1.get(key))[:300],
                                                         json.dumps(c2.get(key))[:300]))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check = None
    if "--check" in argv:
        position = argv.index("--check")
        check = argv[position + 1]
        del argv[position:position + 2]
    digests = [manifest_digest(path) for path in argv]
    for path, digest in zip(argv, digests):
        print("{} {}".format(digest, path))
    status = 0
    if len(set(digests)) > 1:
        print("error: two builds of the same commit gave different images: not reproducible")
        explain_difference(argv[0], argv[1])
        status = 1
    if check and digests:
        with open(check, encoding="utf-8") as handle:
            pinned = json.load(handle)["servers"][0]["image"].split("@", 1)[1]
        if pinned == PLACEHOLDER:
            print("warning: the safety file still pins the placeholder; this build's digest is {}".format(digests[0]))
        elif pinned != digests[0]:
            print("error: the safety file pins {} but this build is {}".format(pinned, digests[0]))
            status = 1
        else:
            print("the safety file pins this build's digest")
    return status


if __name__ == "__main__":
    sys.exit(main())
