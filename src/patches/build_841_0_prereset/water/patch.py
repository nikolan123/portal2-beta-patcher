"""
Fix pre-reset 841_0 water rendering.

- Enable water-surface drawing in both affected client.dll branches.
- Edit toxicslime002a to use proper settings.
"""
from hashlib import sha256
import re

from models import BuildCancelled, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file
from patches.definitions import PatchDefinition

ORIGINAL_CLIENT_SHA256 = "9863b6dea5370d17e793344d7edb1733f63463da97255b0677f1dba36b32c12e"
PATCHED_CLIENT_SHA256 = "04a15f1474ba3341aba2fe1912b514ca0f4e5d6878e21243860a51d5f763d8ce"
CHANGES = ((0x1881E6, 0x30, 0x70), (0x188220, 0x20, 0x60))
MATERIAL_SETTINGS = {
    "$forceexpensive": "1",
    "$basetexture": "Nature/toxicslime002a",
    "$bumpmap": "Nature/slime_normal",
    "$normalmap": "Nature/slime_normal",
    "$normalmapalphaenvmapmask": "1",
    "$surfaceprop": "slime",
    "$envmap": "env_cubemap",
    "$envmaptint": "[ 1.00 0.89 0.80 ]",
    "$envmapcontrast": "1",
    "%keywords": "wasteland",
    "%compileSlime": "1",
    "$reflecttexture": "_rt_WaterReflection",
    "$reflectamount": "0.6",
    "$reflecttint": "{ 0 0 0 }",
    "$reflectskyboxonly": "0",
    "$reflectentities": "1",
    "$abovewater": "1",
    "$bottommaterial": "nature/toxicslime002a_beneath",
    "$fogenable": "1",
    "$fogcolor": "{29 99 39}",
    "$fogstart": "1.00",
    "$fogend": "100.00",
    "$lightmapwaterfog": "1",
}
ANIMATION = '''\t"Proxies"
\t{
\t\t"AnimatedTexture"
\t\t{
\t\t\t"animatedtexturevar" "$normalmap"
\t\t\t"animatedtextureframenumvar" "$bumpframe"
\t\t\t"animatedtextureframerate" "21"
\t\t}
\t}
'''


def patch_material(original: bytes) -> bytes:
    """Change stock flow-map water settings, retaining other text and line endings."""
    newline = "\r\n" if b"\r\n" in original else "\n"
    text = original.decode("utf-8").replace("\r\n", "\n")
    text = text.replace(ANIMATION, "")
    active = re.sub(r"//[^\n]*", "", text)
    structure = re.sub(r'"[^"\n]*"', '""', active)
    if not re.match(r'^\s*"?Water"?\s*\{', active, re.I) or structure.count("{") != 1 or structure.count("}") != 1 or not text.rstrip().endswith("}"):
        raise PatchError("Unexpected goo material structure")
    seen = set()
    lines = []
    for line in text.splitlines(keepends=True):
        match = re.match(r'^\s*"?([\$%][\w]+)"?\s+', line)
        if match:
            key = match[1].lower()
            if key.startswith(("$flow", "$refract")) or key in {"$flashlighttint", "%compilewater", "%tooltexture"}:
                continue
            setting = next((name for name in MATERIAL_SETTINGS if name.lower() == key), None)
            if setting:
                if key in seen:
                    raise PatchError(f"Duplicate goo material setting: {key}")
                seen.add(key)
                line = f'\t"{setting}" "{MATERIAL_SETTINGS[setting]}"\n'
        lines.append(line)
    text = "".join(lines)
    end = text.rfind("}")
    additions = "".join(f'\t"{key}" "{value}"\n' for key, value in MATERIAL_SETTINGS.items() if key.lower() not in seen)
    text = text[:end] + additions + ANIMATION + text[end:]
    return text.replace("\n", newline).encode("utf-8")


def patch_client(original):
    patched = bytearray(original)
    for offset, before, after in CHANGES:
        if offset >= len(patched) or patched[offset] != before:
            raise PatchError("client.dll does not contain the expected water instructions")
        patched[offset] = after
    return bytes(patched)


class Water8410Patch:
    id = "841_0_prereset.water"
    display_name = "Fix Goo Rendering"
    description = "Fix missing water surfaces and restore animated detail."

    def _paths(self, context):
        root = context.root / "game" if (context.root / "game" / "portal2").is_dir() else context.root
        return root / "portal2/bin/client.dll", root / "portal2/materials/nature/toxicslime002a.vmt"

    def check(self, context):
        client, material = self._paths(context)
        if not client.is_file():
            raise PatchError("Pre-reset 841_0 client.dll is missing")
        digest = sha256_file(client)
        if digest not in (ORIGINAL_CLIENT_SHA256, PATCHED_CLIENT_SHA256):
            raise PatchError(f"Refusing to patch unknown client.dll ({digest})")
        if not material.is_file():
            raise PatchError("Stock goo material is missing")
        original = material.read_bytes()
        return digest != PATCHED_CLIENT_SHA256 or patch_material(original) != original

    def apply(self, context, progress):
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        self.check(context)
        client, material = self._paths(context)
        original_material = material.read_bytes()
        data = patch_material(original_material)
        if sha256_file(client) == ORIGINAL_CLIENT_SHA256:
            patched = patch_client(client.read_bytes())
            if sha256(patched).hexdigest() != PATCHED_CLIENT_SHA256:
                raise PatchError("Internal water client.dll verification failed")
            backup_file(client, "client.original.bak", context)
            atomic_write(client, patched)
        if original_material != data:
            backup_file(material, "toxicslime002a.original.bak", context)
            atomic_write(material, data)
        progress(ProgressEvent(self.id, 1, 1, "Fixed water surfaces and material"))

    def verify(self, context):
        client, material = self._paths(context)
        if sha256_file(client) != PATCHED_CLIENT_SHA256 or not material.is_file() or patch_material(material.read_bytes()) != material.read_bytes():
            raise PatchError("Water patch failed verification")


DEFINITION = PatchDefinition(Water8410Patch())
