"""Vendor the shared editor from a local LG Picture Bridge checkout."""

import json
import sys
from hashlib import sha256
from pathlib import Path

root = Path(__file__).resolve().parents[1]
bridge = Path(sys.argv[1]) if len(sys.argv) > 1 else root.parent / "lg-webos-picture-bridge"
target = root / "custom_components/lg_picture_profiles/frontend"
files = {}
for name in ("profile-view.js", "profile-editor.js"):
    source = (bridge / "app" / name).read_bytes()
    (target / name).write_bytes(source)
    files[name] = {"path": "app/" + name, "sha256": sha256(source).hexdigest()}
(target / "editor-source.json").write_text(
    json.dumps({"repository": "andrew-kennedy/lg-webos-picture-bridge", "files": files}) + "\n"
)
