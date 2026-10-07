"""Human VM labels stay separate from libvirt names and filesystem paths."""
import re
import unicodedata
import uuid

from .core import Error


def display_name(value):
    if not isinstance(value, str):
        raise Error("VM-Anzeigenamen mit 1 bis 96 Zeichen angeben.")
    value = value.strip()
    if not 1 <= len(value) <= 96 or any(unicodedata.category(char).startswith("C") for char in value):
        raise Error("VM-Anzeigenamen mit 1 bis 96 sichtbaren Zeichen angeben.")
    return value


def identity(value):
    label = display_name(value)
    if re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", label):
        return label, label
    stem = re.sub(r"[^a-z0-9_-]+", "-", unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()).strip("-_")
    if not stem or not stem[0].isalpha():
        stem = "vm-" + stem
    return stem[:22] + "-" + uuid.uuid4().hex[:8], label


def set_title(root, label):
    title = root.find("title")
    if title is None:
        import xml.etree.ElementTree as ET
        title = ET.SubElement(root, "title")
    title.text = display_name(label)
