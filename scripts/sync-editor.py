"""Vendor the shared editor from a local LG Picture Bridge checkout."""

import sys
from hashlib import sha256
from pathlib import Path

root = Path(__file__).resolve().parents[1]
bridge = Path(sys.argv[1]) if len(sys.argv) > 1 else root.parent / "lg-webos-picture-bridge"
source = (bridge / "app/profile-editor.js").read_bytes()
target = root / "custom_components/lg_picture_profiles/frontend"
(target / "profile-editor.js").write_bytes(source)
(target / "editor-source.json").write_text(
    '{"repository":"andrew-kennedy/lg-webos-picture-bridge","path":"app/profile-editor.js","sha256":"'
    + sha256(source).hexdigest()
    + '"}\n'
)
