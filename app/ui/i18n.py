import json
import os

import streamlit as st

_LOCALES = {}


def _load(lang):
    base = os.path.join(os.path.dirname(__file__), "locales")
    path = os.path.join(base, f"{lang}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def t(key, lang=None, **kwargs):
    lang = lang or st.session_state.get("lang", "en")
    if lang not in _LOCALES:
        _LOCALES[lang] = _load(lang)
    text = _LOCALES[lang].get(key)
    if text is None:
        text = f"??{key}??"
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text
