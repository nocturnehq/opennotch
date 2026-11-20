"""Language for OpenNotch's Settings and island notices: English text is the key, other languages map it."""
import os
import unicodedata

from .lang_el import EL

LANGS = {"el": EL}  # "en" needs no table
_table = {}


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value and value not in ("C", "POSIX"):
            return value.split(":")[0].split(".")[0].split("_")[0].lower()
    return "en"


def setup(choice):
    """choice: 'auto' (follow the desktop), 'en' or 'el'."""
    global _table
    _table = LANGS.get(system_language() if choice == "auto" else choice, {})


def tr(text):
    """The text in the chosen language; untranslated text stays English."""
    return _table.get(text, text) if text else text


def caps(text):
    """Upper case without accents, as Greek capitals are written (ΓΛΩΣΣΑ, not ΓΛΏΣΣΑ)."""
    return unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", text.upper())
                                               if c not in "\u0301\u0344"))
