"""Language tags as other tools write them -> the codes Vitra accepts.

Vitra checks every language in an imported file against its language list
(languages.json beside this file, a copy of the server's list). A code outside
that list fails the whole import, so every tag is resolved here first.
"""

from __future__ import annotations

import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, "languages.json"), encoding="utf-8") as _fh:
    _CATALOG = json.load(_fh)

CODES: set[str] = {x["code"] for x in _CATALOG}
_BY_LOWER = {c.lower(): c for c in CODES}
LABELS: dict[str, str] = {x["code"]: x["label"] for x in _CATALOG}
_BY_LABEL: dict[str, str] = {}
for _x in _CATALOG:
    for _k in (_x["label"], _x["name"], _x["name"].replace("_", " ")):
        if _k:
            _BY_LABEL.setdefault(_k.strip().lower(), _x["code"])

# Old, three-letter and vendor spellings people still export.
_ALIASES = {
    "iw": "he", "in": "id", "ji": "yi", "jw": "jv", "mo": "ro",
    "zh-chs": "zh-Hans", "zh-cht": "zh-Hant", "zh-hans-cn": "zh-CN", "zh-hant-tw": "zh-TW",
    "zh-hant-hk": "zh-HK", "eng": "en", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr",
    "spa": "es", "ita": "it", "por": "pt", "nld": "nl", "dut": "nl", "jpn": "ja", "kor": "ko",
    "zho": "zh", "chi": "zh", "rus": "ru", "ara": "ar", "hin": "hi", "ben": "bn", "tam": "ta",
    "tel": "te", "mar": "mr", "guj": "gu", "kan": "kn", "mal": "ml", "pan": "pa", "urd": "ur",
    "tur": "tr", "pol": "pl", "swe": "sv", "dan": "da", "nor": "no", "fin": "fi", "ces": "cs",
    "cze": "cs", "ell": "el", "gre": "el", "heb": "he", "hun": "hu", "ron": "ro", "rum": "ro",
    "ukr": "uk", "vie": "vi", "tha": "th", "ind": "id", "msa": "ms", "may": "ms",
}

# Language names some tools write instead of codes ("German", "Chinese (Simplified)").
_NAMES = {
    "chinese (simplified)": "zh-Hans", "chinese simplified": "zh-Hans", "simplified chinese": "zh-Hans",
    "chinese (traditional)": "zh-Hant", "chinese traditional": "zh-Hant",
    "traditional chinese": "zh-Hant", "english (us)": "en-US", "english (uk)": "en-GB",
    "brazilian portuguese": "pt-BR", "portuguese (brazil)": "pt-BR", "latin american spanish": "es-419",
    "spanish (latin america)": "es-419", "norwegian": "nb", "norwegian (bokmal)": "nb",
    "norwegian bokmal": "nb", "filipino": "fil", "tagalog": "tl", "farsi": "fa", "persian": "fa",
}

_TAG = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8})*$")

# "German (Germany)", "Chinese (Traditional, Taiwan)": names split into language,
# script and region, learned from Vitra's own labels plus the spellings Windows,
# MultiTerm and Trados use.
_LANG_NAMES: dict[str, str] = {}
_REGION_NAMES: dict[str, str] = {
    "korea": "KR", "republic of korea": "KR", "uae": "AE", "u.a.e.": "AE", "czech republic": "CZ",
    "czechia": "CZ", "prc": "CN", "people's republic of china": "CN", "usa": "US", "us": "US",
    "u.s.": "US", "uk": "GB", "great britain": "GB", "britain": "GB", "taiwan": "TW", "hong kong": "HK",
    "hong kong sar": "HK", "hong kong s.a.r.": "HK", "macao s.a.r.": "MO", "macao sar": "MO", "macau": "MO", "latin america": "419",
    "latin america and caribbean": "419", "international sort": "ES", "traditional sort": "ES",
    "brasil": "BR", "the netherlands": "NL", "holland": "NL", "russia": "RU", "vietnam": "VN",
    "viet nam": "VN", "iran": "IR", "turkiye": "TR", "türkiye": "TR",
}
_SCRIPTS = {"simplified": "Hans", "traditional": "Hant", "latin": "Latn", "cyrillic": "Cyrl",
            "arabic": "Arab", "devanagari": "Deva", "cyrl": "Cyrl", "latn": "Latn"}
for _x in _CATALOG:
    _parts = _x["code"].split("-")
    _base = _x["label"].split(" (")[0].strip().lower()
    if len(_parts) == 1 and _base:
        _LANG_NAMES.setdefault(_base, _x["code"])
    _m = re.match(r"^[^(]*\(([^(),]+)\)$", _x["label"])
    if _m and len(_parts) >= 2 and re.fullmatch(r"[A-Z]{2}|\d{3}", _parts[-1]):
        _REGION_NAMES.setdefault(_m.group(1).strip().lower(), _parts[-1])
_LANG_NAMES.update({"norwegian": "no", "chinese": "zh", "farsi": "fa", "persian": "fa",
                    "tagalog": "tl", "filipino": "fil", "malay": "ms", "hebrew": "he"})


def _from_name(s: str) -> str | None:
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", s)
    base = (m.group(1) if m else s).strip().lower()
    quals = [q.strip().lower() for q in m.group(2).split(",")] if m else []
    lang = _LANG_NAMES.get(base)
    if not lang:
        return None
    script = region = None
    same_as_language = False
    for q in quals:
        if q in ("bokmal", "bokmål"):
            lang = "nb"
        elif q == "nynorsk":
            lang = "nn"
        elif q in _SCRIPTS:
            script = _SCRIPTS[q]
        elif q in _REGION_NAMES:
            region = _REGION_NAMES[q]
        elif q == base:
            same_as_language = True
        else:
            return None
    if same_as_language and not region:
        # "Catalan (Catalan)", "Basque (Basque)": the language's one regional variant.
        home = {"ca": "ca-ES", "eu": "eu-ES", "gl": "gl-ES"}.get(lang)
        if home in CODES:
            return home
        variants = [c for c in CODES if c.startswith(lang + "-") and re.fullmatch(r"[a-z]+-[A-Z]{2}", c)]
        return variants[0] if len(variants) == 1 else (lang if lang in CODES else None)
    cands = []
    if lang == "zh" and region:
        # Chinese is written zh-CN / zh-TW / zh-HK far more often than with its script.
        cands.append(f"zh-{region}")
    if script and region:
        cands.append(f"{lang}-{script}-{region}")
    if region:
        cands.append(f"{lang}-{region}")
    elif script:
        cands.append(f"{lang}-{script}")
    else:
        cands.append(lang)
    return next((c for c in cands if c in CODES), None)


def canonical(tag: str) -> str:
    """BCP-47 casing, the way Vitra spells it: en-us -> en-US, zh_hant -> zh-Hant."""
    parts = tag.replace("_", "-").split("-")
    out = [parts[0].lower()]
    for p in parts[1:]:
        if re.fullmatch(r"[A-Za-z]{2}", p):
            out.append(p.upper())
        elif re.fullmatch(r"[A-Za-z]{4}", p):
            out.append(p[0].upper() + p[1:].lower())
        else:
            out.append(p.lower())
    return "-".join(out)


def looks_like_tag(text: str) -> bool:
    return bool(_TAG.match(text.strip()))


def resolve(raw: str, overrides: dict[str, str] | None = None) -> str | None:
    """A Vitra language code for `raw`, or None when there is none.

    Order: the user's own mapping, an exact code, the same code in other
    casing, a known alias, a language name from Vitra's list. Never a guess
    between regions: "es" stays "es", it is not turned into es-ES.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if overrides:
        for key in (s, s.lower(), canonical(s) if looks_like_tag(s) else None):
            if key and key in overrides:
                return overrides[key]
        low = {k.lower(): v for k, v in overrides.items()}
        if s.lower() in low:
            return low[s.lower()]
    if s in CODES:
        return s
    low = s.lower().replace("_", "-")
    if low in _BY_LOWER:
        return _BY_LOWER[low]
    if low in _ALIASES:
        a = _ALIASES[low]
        return _BY_LOWER.get(a.lower())
    if looks_like_tag(s):
        head, _, rest = low.partition("-")
        if head in _ALIASES and rest:
            cand = f"{_ALIASES[head]}-{rest}"
            if cand in _BY_LOWER:
                return _BY_LOWER[cand]
        return None
    name = re.sub(r"\s+", " ", s.lower())
    if name in _NAMES:
        return _NAMES[name] if _NAMES[name] in CODES else None
    if name in _BY_LABEL:
        return _BY_LABEL[name]
    return _from_name(s)


def label(code: str) -> str:
    return LABELS.get(code, code)


def parse_map(pairs: list[str] | None) -> dict[str, str]:
    """`--lang-map en=en-US --lang-map "English=en-GB"` -> {raw: code}; codes are checked."""
    out: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--lang-map needs FROM=TO, got '{pair}'")
        src, dst = (p.strip() for p in pair.split("=", 1))
        code = dst if dst in CODES else _BY_LOWER.get(dst.lower().replace("_", "-"))
        if not code:
            raise ValueError(f"--lang-map: '{dst}' is not a language code Vitra accepts")
        out[src] = code
        out[src.lower()] = code
    return out
