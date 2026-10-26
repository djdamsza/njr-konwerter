"""Czyści tytuł i wykonawcę ze śmieci. Zostawia wersję utworu i nazwę w nawiasie."""
import re
from difflib import SequenceMatcher

_URL = re.compile(r'(?:https?://|www\.)\S+|\byoutu\.be/\S+', re.IGNORECASE)
_EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
_HASH = re.compile(r'(?<!\w)#[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+', re.UNICODE)
_LOOSE = re.compile(
    r'\b(?:official\s+(?:music\s+)?(?:video|audio|mv)|official\s+lyric\s+video|'
    r'lyric\s+video|free\s+download|official\s+teledysk)\b',
    re.IGNORECASE,
)
_PROTECT = re.compile(
    r'\b(?:remix(?:es|ed)?|mix(?:ed)?|edits?|versions?|extended|radio|club|dub|'
    r'instrumentals?|acoustics?|remasters?|remastered|live|feat(?:uring)?|ft|'
    r'vip|bootlegs?|reworks?|flips?|covers?|mash-?ups?|sped|slowed|nightcore|'
    r'prod(?:uced)?|soundtrack|ost|explicit|clean|dirty|acapellas?|'
    r'a\s*cappellas?)\b',
    re.IGNORECASE,
)
_JUNK_HINT = re.compile(
    r'official|videos?|teledysk|lyrics?|visuali[sz]|youtu\.?be|download|'
    r'\b(?:hd|hq|4k|1080p|720p|mp3|wav|audio|clip|mv)\b|'
    r'tekst(?:\s+piosenki)?|s[łl]owa|premiera|subscri\w*|subskryb',
    re.IGNORECASE,
)
_WRAPPER = re.compile(r'\(([^)]*)\)|\[([^\]]*)\]')
_EDGE = re.compile(r'^[\s\-–—|,:;/]+|[\s\-–—|,:;/]+$')


def _paren_is_junk(inner: str) -> bool:
    text = (inner or '').strip()
    if not text:
        return True
    if _PROTECT.search(text):
        return False
    return _JUNK_HINT.search(text) is not None


def _strip_wrappers(value: str) -> str:
    def repl(match: re.Match) -> str:
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        return ' ' if _paren_is_junk(inner) else match.group(0)

    current = value
    for _ in range(4):
        nxt = _WRAPPER.sub(repl, current)
        if nxt == current:
            break
        current = nxt
    return current


def clean_junk(value: str) -> str:
    """Zdejmuje mail, link, hashtag i dopisek z YouTube. Remix, Radio Edit i nazwa w nawiasie zostają."""
    text = (value or '').strip()
    if not text:
        return text
    text = _EMAIL.sub(' ', text)
    text = _URL.sub(' ', text)
    text = _HASH.sub(' ', text)
    text = _LOOSE.sub(' ', text)
    text = _strip_wrappers(text)
    text = re.sub(r'\s+', ' ', text)
    text = _EDGE.sub('', text).strip()
    return text


def diff_marks(before: str, after: str) -> list[dict]:
    """Kawałki linii „przed”: drop=True to fragment, który schodzi."""
    marks = []
    for tag, i1, i2, _j1, _j2 in SequenceMatcher(a=before or '', b=after or '').get_opcodes():
        if tag == 'equal':
            piece = before[i1:i2]
            if piece:
                marks.append({'t': piece, 'drop': False})
        elif tag in ('delete', 'replace'):
            piece = before[i1:i2]
            if piece:
                marks.append({'t': piece, 'drop': True})
    return marks
