import re
import unicodedata


MAX_FOCUS_WORDS = 4
MAX_SLUG_WORDS = 4
MAX_META_DESCRIPTION_CHARS = 156
MAX_SEO_TITLE_CHARS = 60


STOPWORDS = {
    "pt": {
        "de", "da", "do", "das", "dos", "e", "em", "para", "por", "com", "a", "o", "as", "os", "um", "uma",
        "sobre", "no", "na", "nos", "nas"
    },
    "es": {
        "de", "del", "la", "el", "las", "los", "y", "en", "para", "por", "con", "un", "una", "sobre"
    },
    "fr": {
        "de", "du", "des", "la", "le", "les", "et", "en", "pour", "par", "avec", "un", "une", "sur"
    },
    "en": {
        "the", "a", "an", "and", "in", "for", "of", "to", "with", "on", "about"
    }
}


PREFERRED_TERMS = {
    "pt": ["polígrafo", "fraude", "furto", "infidelidade", "empresas", "corporativo", "interno"],
    "es": ["polígrafo", "fraude", "hurto", "infidelidad", "empresas", "corporativo", "interno"],
    "fr": ["polygraphe", "fraude", "vol", "infidélité", "entreprise", "interne"],
    "en": ["polygraph", "fraud", "theft", "infidelity", "business", "corporate", "internal"],
}


def normalize_language(language):
    language = str(language or "en").lower()

    if language.startswith("pt"):
        return "pt"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"

    return "en"


def strip_accents(text):
    text = str(text or "")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def clean_text(text):
    text = str(text or "").strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"#+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;|-–—")


def words_from_text(text):
    text = clean_text(text)
    return re.findall(r"[\wÀ-ÿ]+", text, flags=re.UNICODE)


def truncate_words(text, max_words):
    words = words_from_text(text)
    return " ".join(words[:max_words]).strip()


def smart_focus_keyphrase(source, language="en", max_words=MAX_FOCUS_WORDS):
    language = normalize_language(language)
    words = words_from_text(source)

    if not words:
        return ""

    stopwords = STOPWORDS.get(language, STOPWORDS["en"])
    preferred = PREFERRED_TERMS.get(language, PREFERRED_TERMS["en"])

    selected = []

    lower_words = [w.lower() for w in words]

    for term in preferred:
        if term.lower() in lower_words and term.lower() not in [s.lower() for s in selected]:
            original = words[lower_words.index(term.lower())]
            selected.append(original)

        if len(selected) >= max_words:
            break

    if len(selected) < max_words:
        for word in words:
            word_lower = word.lower()

            if word_lower in stopwords:
                continue

            if word_lower not in [s.lower() for s in selected]:
                selected.append(word)

            if len(selected) >= max_words:
                break

    if not selected:
        selected = words[:max_words]

    return " ".join(selected[:max_words]).strip()


def enforce_focus_keyphrase(value, fallback="", language="en"):
    source = value or fallback
    return smart_focus_keyphrase(source, language=language, max_words=MAX_FOCUS_WORDS)


def slugify_limited(value, fallback="", language="en", max_words=MAX_SLUG_WORDS):
    phrase = enforce_focus_keyphrase(value, fallback=fallback, language=language)
    phrase = strip_accents(phrase).lower()
    phrase = re.sub(r"[^a-z0-9]+", "-", phrase)
    phrase = re.sub(r"-+", "-", phrase).strip("-")

    parts = [p for p in phrase.split("-") if p]
    return "-".join(parts[:max_words]) or "seo-page"


def truncate_chars(text, max_chars):
    text = clean_text(text)

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rsplit(" ", 1)[0].strip(" .,:;")[:max_chars]


def enforce_seo_title(value, fallback="", language="en"):
    text = clean_text(value or fallback)

    if not text:
        text = enforce_focus_keyphrase(fallback, language=language).title()

    return truncate_chars(text, MAX_SEO_TITLE_CHARS)


def enforce_meta_description(value, fallback="", focus_keyphrase="", language="en"):
    text = clean_text(value)

    if not text:
        focus = focus_keyphrase or enforce_focus_keyphrase(fallback, language=language)

        if normalize_language(language) == "pt":
            text = f"{focus}: avaliação profissional, confidencial e conduzida por examinador qualificado."
        elif normalize_language(language) == "es":
            text = f"{focus}: evaluación profesional, confidencial y realizada por un examinador cualificado."
        elif normalize_language(language) == "fr":
            text = f"{focus}: évaluation professionnelle, confidentielle et menée par un examinateur qualifié."
        else:
            text = f"{focus}: professional, confidential assessment conducted by a qualified examiner."

    return truncate_chars(text, MAX_META_DESCRIPTION_CHARS)


def normalize_seo_fields(
    title="",
    focus_keyphrase="",
    slug="",
    meta_description="",
    seo_title="",
    fallback_topic="",
    language="en"
):
    language = normalize_language(language)

    source = fallback_topic or title or focus_keyphrase or slug

    clean_focus = enforce_focus_keyphrase(
        focus_keyphrase,
        fallback=source,
        language=language
    )

    clean_slug = slugify_limited(
        slug or clean_focus,
        fallback=source,
        language=language
    )

    clean_seo_title = enforce_seo_title(
        seo_title or title,
        fallback=source,
        language=language
    )

    clean_meta = enforce_meta_description(
        meta_description,
        fallback=source,
        focus_keyphrase=clean_focus,
        language=language
    )

    return {
        "focus_keyphrase": clean_focus,
        "slug": clean_slug,
        "seo_title": clean_seo_title,
        "meta_description": clean_meta
    }