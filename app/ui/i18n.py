import json
import os

import streamlit as st

_LOCALES = {}


def _load(lang):
    base = os.path.join(os.path.dirname(__file__), "locales")
    path = os.path.join(base, f"{lang}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def t(msgid=None, lang=None, *, key=None, **kwargs):
    if msgid is None:
        msgid = key
    if msgid is None:
        return "????"
    lang = lang or st.session_state.get("lang", "en")
    if lang not in _LOCALES:
        _LOCALES[lang] = _load(lang)
    text = _LOCALES[lang].get(msgid)
    if text is None:
        text = f"??{msgid}??"
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text
