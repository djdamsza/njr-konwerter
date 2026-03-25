"""
Generator master.db Rekordbox (File → Library → Restore Library).
Tworzy bazę SQLite (SQLCipher4) z UnifiedDatabase do pełnej migracji VDJ → RB.
Rekordbox wymaga zaszyfrowanej bazy – używamy klucza z pyrekordbox.
"""
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pyrekordbox.db6 import tables
from unified_model import UnifiedDatabase, Track, Playlist, CuePoint
from vdjfolder import normalize_path

try:
    from file_analyzer import read_file_metadata
except ImportError:
    read_file_metadata = None

# SQLCipher – wymagany dla Restore Library (RB nie otwiera plain SQLite)
try:
    from sqlcipher3 import dbapi2 as _sqlcipher
    from pyrekordbox.utils import deobfuscate
    from pyrekordbox.db6.database import BLOB
    _RB_KEY = deobfuscate(BLOB)
    _SQLCIPHER_AVAILABLE = True
except Exception:
    _sqlcipher = None
    _RB_KEY = ""
    _SQLCIPHER_AVAILABLE = False

# Mapowanie rozszerzeń na FileType RB (backup: mp3=1, m4a=4, flac=5, wav=11)
_FILETYPE_MAP = {
    ".mp3": 1,
    ".m4a": 4,
    ".aac": 4,
    ".flac": 5,
    ".wav": 11,
    ".aiff": 12,
    ".aif": 12,
}


def _make_id_generator():
    """Generator unikalnych ID – licznik eliminuje kolizje przy dużej liczbie rekordów."""
    base = int(time.time() * 1000) * 100000
    counter = [0]

    def _next() -> str:
        counter[0] += 1
        return str(base + counter[0])
    return _next


def _path_transform(path: str, path_replace: Optional[dict]) -> tuple[str, str]:
    """
    Zwraca (FolderPath, FileNameL) dla djmdContent.
    RB oczekuje: FolderPath = PEŁNA ścieżka do pliku (włącznie z nazwą), FileNameL = nazwa pliku.
    Dla Tidal: FolderPath = "tidal:tracks:123", FileNameL = "123" (tylko ID).
    path_replace: {old_prefix: new_prefix} do zamiany ścieżki.
    """
    if path_replace:
        for old_prefix, new_prefix in path_replace.items():
            if path.startswith(old_prefix):
                path = new_prefix + path[len(old_prefix) :]
                break
    # Tidal: tidal:tracks:330964 → FolderPath=tidal:tracks:330964, FileNameL=330964
    if path.startswith("tidal:tracks:"):
        tid = path[len("tidal:tracks:") :].strip()
        return path, tid if tid.isdigit() else path
    # file:// – zachowaj dokładny zapis
    if path.startswith("file:"):
        idx = path.rfind("/")
        if idx >= 0:
            return path, path[idx + 1 :]
    p = Path(path)
    full_path = str(p).replace("\\", "/")
    return full_path, p.name


def _get_filetype(path: str) -> int:
    ext = Path(path).suffix.lower()
    return _FILETYPE_MAP.get(ext, 0)


def _read_file_meta(path: str) -> tuple[int, float, int, int]:
    """Size, duration (s), bitrate (kbps), sample_rate. Dla Tidal/streaming zwraca 0."""
    if not path or path.startswith("tidal:") or path.startswith("td") or path.startswith("netsearch:"):
        return 0, 0.0, 0, 0
    try:
        p = Path(path)
        if not p.exists():
            return 0, 0.0, 0, 0
        size = p.stat().st_size
        ext = p.suffix.lower()
        duration, bitrate, sample_rate = 0.0, 0, 0
        if ext in (".mp3", ".mp2", ".mp1"):
            from mutagen.mp3 import MP3
            audio = MP3(path)
            duration = audio.info.length
            bitrate = int(audio.info.bitrate / 1000) if audio.info.bitrate else 0
            sample_rate = audio.info.sample_rate or 0
        elif ext in (".m4a", ".mp4", ".aac"):
            from mutagen.mp4 import MP4
            audio = MP4(path)
            duration = audio.info.length
            if hasattr(audio.info, "bitrate") and audio.info.bitrate:
                bitrate = int(audio.info.bitrate / 1000)
            if hasattr(audio.info, "sample_rate") and audio.info.sample_rate:
                sample_rate = audio.info.sample_rate
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(path)
            duration = audio.info.length
            if hasattr(audio.info, "sample_rate") and audio.info.sample_rate:
                sample_rate = audio.info.sample_rate
                bitrate = int(sample_rate * 16 * 2 / 1000) if sample_rate else 0
        elif ext == ".wav":
            from mutagen.wave import WAVE
            audio = WAVE(path)
            duration = audio.info.length
            sample_rate = audio.info.sample_rate or 0
            bitrate = int(sample_rate * 16 * 2 / 1000) if sample_rate else 0
        return size, duration, bitrate, sample_rate or 44100
    except Exception:
        return 0, 0.0, 0, 0


def _normalize_key(key: str) -> str:
    """Normalizuje tonację do formatu RB (np. Cmajor -> C, Am -> Am)."""
    if not key or not key.strip():
        return ""
    k = key.strip()
    # Usuń 'major'/'minor' jeśli jest
    k = k.replace("major", "").replace("Major", "").strip()
    k = k.replace("minor", "m").replace("Minor", "m").strip()
    return k[:10] if k else ""


def _now_dt() -> datetime:
    """Datetime UTC dla created_at/updated_at (pyrekordbox wymaga datetime)."""
    return datetime.now(timezone.utc)


def _generate_uuid() -> str:
    return str(uuid.uuid4()).lower()


def unified_to_master_db(
    db: UnifiedDatabase,
    path_replace: Optional[dict] = None,
    output_path: Optional[str] = None,
    template_path: Optional[str] = None,
    skip_my_tags: bool = False,
) -> bytes:
    """
    Generuje master.db z UnifiedDatabase.
    path_replace: {old_prefix: new_prefix} do zamiany ścieżek plików.
    output_path: opcjonalna ścieżka do zapisu (inaczej zwraca bytes).
    template_path: ścieżka do backupu RB (ZIP) lub master.db – zachowuje oryginalne szyfrowanie RB.
    Zwraca: bytes zawartości master.db.
    """
    import tempfile
    import shutil
    import zipfile
    from sqlalchemy import text
    from pyrekordbox.db6.database import Rekordbox6Database

    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    db_path = tmp_db.name
    _next_id = _make_id_generator()

    if template_path:
        # Szablon z backupu RB – zachowuje oryginalne szyfrowanie (RB wymaga SQLCipher4)
        template = Path(template_path).expanduser().resolve()
        if not template.exists():
            raise FileNotFoundError(f"Szablon nie istnieje: {template}")
        if template.suffix.lower() == ".zip":
            with zipfile.ZipFile(template, "r") as zf:
                master_data = None
                for name in zf.namelist():
                    if name.endswith("master.db") or name.split("/")[-1] == "master.db":
                        master_data = zf.read(name)
                        break
                if not master_data:
                    raise ValueError("W ZIP nie znaleziono master.db")
            Path(db_path).write_bytes(master_data)
        else:
            shutil.copy2(template, db_path)
        rb_db = Rekordbox6Database(db_path, unlock=True)
        session = rb_db.session
        engine = None
        # Usuń zawartość – zachowaj schemat i szyfrowanie
        # djmdSongMyTag/djmdMyTag – stare wpisy odwołują się do usuniętych ContentID (sieroty blokują RB)
        for table in (
            "djmdCue", "djmdSongPlaylist", "contentCue", "contentFile", "djmdContent",
            "djmdPlaylist", "djmdArtist", "djmdAlbum", "djmdGenre", "djmdKey", "djmdColor",
            "djmdSongMyTag", "djmdMyTag",  # sieroty po usunięciu Content
            "djmdSongHistory", "djmdActiveCensor", "djmdSongRelatedTracks",
            "djmdSongHotCueBanklist", "djmdSongSampler", "djmdSongTagList",
        ):
            try:
                session.execute(text(f"DELETE FROM {table}"))
            except Exception:
                pass
        session.commit()

        # Odczytaj DeviceID i DBID z DjmdProperty – format jak w backupie MIXO
        device_id = ""
        dbid = ""
        try:
            r = session.execute(text("SELECT DeviceID, DBID FROM DjmdProperty LIMIT 1"))
            row = r.fetchone()
            if row:
                if row[0]:
                    device_id = str(row[0])
                if len(row) > 1 and row[1]:
                    dbid = str(row[1])
        except Exception:
            pass
    else:
        rb_db = None
        device_id = ""
        dbid = ""
        if not _SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                "Brak sqlcipher3. Użyj szablonu: podaj ścieżkę do backupu RB (File → Backup Library)."
            )
        url = f"sqlite+pysqlcipher://:{_RB_KEY}@/{db_path}?"
        engine = create_engine(url, module=_sqlcipher)
        meta = tables.DjmdContent.metadata
        meta.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

    # Słowniki deduplikacji: wartość -> ID
    artist_ids: dict[str, str] = {}
    album_ids: dict[str, str] = {}
    genre_ids: dict[str, str] = {}
    key_ids: dict[str, str] = {}

    # Wstaw domyślne kolory (RB ma 1-8)
    for i, name in enumerate(
        ["Pink", "Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple"], 1
    ):
        c = tables.DjmdColor(
            ID=str(i),
            ColorCode=0,
            SortKey=i,
            Commnt=name,
            UUID=_generate_uuid(),
            rb_data_status=0,
            rb_local_data_status=0,
            rb_local_deleted=0,
            rb_local_synced=0,
            usn=0,
            rb_local_usn=0,
            created_at=_now_dt(),
            updated_at=_now_dt(),
        )
        session.add(c)
    session.commit()

    # Domyślne tonacje RB (1-24) – używamy ich gdy pasują
    default_keys = [
        "Fm", "Cm", "A", "E", "Am", "Gm", "F#m", "Ebm", "G#", "Bm", "C#m", "C#",
        "F#", "F", "Dm", "B", "Em", "Ab", "Db", "Eb", "D", "Abm", "Bb", "C",
    ]
    default_key_ids = {name: str(i) for i, name in enumerate(default_keys[:24], 1)}
    for i, scale in enumerate(default_keys[:24], 1):
        k = tables.DjmdKey(
            ID=str(i),
            ScaleName=scale,
            Seq=i,
            UUID=_generate_uuid(),
            rb_data_status=0,
            rb_local_data_status=0,
            rb_local_deleted=0,
            rb_local_synced=0,
            usn=0,
            rb_local_usn=0,
            created_at=_now_dt(),
            updated_at=_now_dt(),
        )
        session.add(k)
    session.commit()

    # Zbierz unikalne wartości z utworów
    for t in db.tracks:
        if t.artist and t.artist.strip() and t.artist not in artist_ids:
            artist_ids[t.artist] = _next_id()
        if t.album and t.album.strip() and t.album not in album_ids:
            album_ids[t.album] = _next_id()
        if t.genre and t.genre.strip() and t.genre not in genre_ids:
            genre_ids[t.genre] = _next_id()
        nk = _normalize_key(t.key)
        if nk and nk not in key_ids:
            key_ids[nk] = default_key_ids.get(nk) or _next_id()

    # Wstaw djmdArtist (SearchStr NOT NULL w schemacie pyrekordbox)
    for name, aid in artist_ids.items():
        a = tables.DjmdArtist(
            ID=aid,
            Name=name,
            SearchStr=name or "",
            UUID=_generate_uuid(),
            rb_data_status=0,
            rb_local_data_status=0,
            rb_local_deleted=0,
            rb_local_synced=0,
            usn=0,
            rb_local_usn=0,
            created_at=_now_dt(),
            updated_at=_now_dt(),
        )
        session.add(a)
    session.commit()

    # Wstaw djmdAlbum (wszystkie NOT NULL w schemacie)
    for name, aid in album_ids.items():
        a = tables.DjmdAlbum(
            ID=aid,
            Name=name,
            AlbumArtistID="",
            ImagePath="",
            Compilation=0,
            SearchStr=name or "",
            UUID=_generate_uuid(),
            rb_data_status=0,
            rb_local_data_status=0,
            rb_local_deleted=0,
            rb_local_synced=0,
            usn=0,
            rb_local_usn=0,
            created_at=_now_dt(),
            updated_at=_now_dt(),
        )
        session.add(a)
    session.commit()

    # Wstaw djmdGenre
    for name, gid in genre_ids.items():
        g = tables.DjmdGenre(
            ID=gid,
            Name=name,
            UUID=_generate_uuid(),
            rb_data_status=0,
            rb_local_data_status=0,
            rb_local_deleted=0,
            rb_local_synced=0,
            usn=0,
            rb_local_usn=0,
            created_at=_now_dt(),
            updated_at=_now_dt(),
        )
        session.add(g)
    session.commit()

    # Wstaw djmdKey dla niestandardowych tonacji (nie w domyślnych)
    for name, kid in key_ids.items():
        if name not in default_keys:
            k = tables.DjmdKey(
                ID=kid,
                ScaleName=name,
                Seq=100,
                UUID=_generate_uuid(),
                rb_data_status=0,
                rb_local_data_status=0,
                rb_local_deleted=0,
                rb_local_synced=0,
                usn=0,
                rb_local_usn=0,
                created_at=_now_dt(),
                updated_at=_now_dt(),
            )
            session.add(k)
    session.commit()

    # Mapowanie path -> ContentID (używamy znormalizowanych ścieżek – dopasowanie do vdjfolder)
    path_to_content_id: dict[str, str] = {}
    path_to_uuid: dict[str, str] = {}

    # Wstaw djmdContent
    for i, t in enumerate(db.tracks):
        content_id = _next_id()
        content_uuid = _generate_uuid()
        np = normalize_path(t.path)
        path_to_content_id[np] = content_id
        path_to_uuid[np] = content_uuid

        folder_path, file_name = _path_transform(t.path, path_replace)
        artist_id = artist_ids.get(t.artist) if t.artist else None
        album_id = album_ids.get(t.album) if t.album else None
        genre_id = genre_ids.get(t.genre) if t.genre else None
        nk = _normalize_key(t.key)
        key_id = key_ids.get(nk) if nk else None

        # RB wymaga FileSize, BitRate, SampleRate – bez nich może pokazywać czerwone ikony
        # Używamy folder_path (po path_replace) – to ścieżka, którą RB będzie szukał
        file_size, file_dur, bit_rate, sample_rate = _read_file_meta(folder_path)
        length_val = int(file_dur) if file_dur else (int(t.duration) if t.duration else 0)

        # Gdy plik istnieje – używaj tytułu/artysty/albumu Z PLIKU, żeby rekord zgadzał się z odtwarzanym utworem
        title_val = t.title or Path(t.path).stem
        artist_id_val = artist_id
        album_id_val = album_id
        genre_id_val = genre_id
        src_artist_val = (t.artist or "")[:1024]
        if file_size > 0 and read_file_metadata:
            try:
                f_artist, f_title, f_album, f_genre, _, _ = read_file_metadata(folder_path)
                if f_title and f_title.strip():
                    title_val = f_title.strip()[:1024]
                if f_artist and f_artist.strip():
                    src_artist_val = f_artist.strip()[:1024]
                    if f_artist not in artist_ids:
                        aid = _next_id()
                        artist_ids[f_artist] = aid
                        session.add(tables.DjmdArtist(
                            ID=aid, Name=f_artist, SearchStr=f_artist or "",
                            UUID=_generate_uuid(), rb_data_status=0, rb_local_data_status=0,
                            rb_local_deleted=0, rb_local_synced=0, usn=0, rb_local_usn=0,
                            created_at=_now_dt(), updated_at=_now_dt(),
                        ))
                    artist_id_val = artist_ids.get(f_artist)
                if f_album and f_album.strip() and f_album not in album_ids:
                    aid = _next_id()
                    album_ids[f_album] = aid
                    session.add(tables.DjmdAlbum(
                        ID=aid, Name=f_album, AlbumArtistID="", ImagePath="", Compilation=0,
                        SearchStr=f_album or "", UUID=_generate_uuid(), rb_data_status=0,
                        rb_local_data_status=0, rb_local_deleted=0, rb_local_synced=0,
                        usn=0, rb_local_usn=0, created_at=_now_dt(), updated_at=_now_dt(),
                    ))
                    album_id_val = album_ids.get(f_album)
                elif f_album and f_album.strip():
                    album_id_val = album_ids.get(f_album)
                if f_genre and f_genre.strip() and f_genre not in genre_ids:
                    gid = _next_id()
                    genre_ids[f_genre] = gid
                    session.add(tables.DjmdGenre(
                        ID=gid, Name=f_genre, UUID=_generate_uuid(), rb_data_status=0,
                        rb_local_data_status=0, rb_local_deleted=0, rb_local_synced=0,
                        usn=0, rb_local_usn=0, created_at=_now_dt(), updated_at=_now_dt(),
                    ))
                    genre_id_val = genre_ids.get(f_genre)
                elif f_genre and f_genre.strip():
                    genre_id_val = genre_ids.get(f_genre)
            except Exception:
                pass

        # Commnt = VDJ Comment (nie tagi – tagi idą do My Tags)
        comments = (t.comment or "")[:1024]

        # Wszystkie kolumny NOT NULL w schemacie pyrekordbox – używamy ""/0
        c = tables.DjmdContent(
            ID=content_id,
            FolderPath=folder_path,
            FileNameL=file_name,
            FileNameS=file_name[:12] if len(file_name) > 12 else file_name,
            Title=title_val,
            ArtistID=artist_id_val,
            AlbumID=album_id_val,
            GenreID=genre_id_val,
            BPM=int(round(t.bpm * 100)) if t.bpm else 0,  # RB: BPM*100 (120→12000)
            Length=length_val,
            TrackNo=0,
            BitRate=bit_rate,
            BitDepth=0,
            Commnt=comments[:1024] if comments else "",
            FileType=_get_filetype(t.path),
            Rating=t.rating or 0,
            ReleaseYear=t.year if t.year else 0,
            RemixerID=None,
            LabelID=None,
            OrgArtistID=None,
            KeyID=key_id,
            StockDate=datetime.now(timezone.utc).strftime("%Y-%m-%d") if file_size > 0 else "",
            ColorID="0",
            DJPlayCount=t.play_count or 0,
            ImagePath="",
            MasterDBID=dbid or "",
            MasterSongID=content_id,  # MIXO: = ID
            AnalysisDataPath="",
            SearchStr=f"{title_val or ''} {src_artist_val or ''}".strip()[:255] or "",
            FileSize=file_size,
            DiscNo=0,
            ComposerID=None,
            Subtitle="",
            SampleRate=sample_rate,
            DisableQuantize=0,
            Analysed=105 if file_size > 0 else 0,  # backup MIXO: 105 gdy plik istnieje
            ReleaseDate="",
            DateCreated=datetime.now(timezone.utc).strftime("%Y-%m-%d") if file_size > 0 else "",
            ContentLink=0,
            Tag="",
            ModifiedByRBM="",
            HotCueAutoLoad="on" if file_size > 0 else "",
            DeliveryControl="on" if file_size > 0 else "",
            DeliveryComment="",
            CueUpdated="",
            AnalysisUpdated="2" if file_size > 0 else "",
            TrackInfoUpdated="2" if file_size > 0 else "",
            Lyricist="",
            ISRC="",
            SamplerTrackInfo=0,
            SamplerPlayOffset=0,
            SamplerGain=0.0,
            VideoAssociate="",
            LyricStatus=0,
            ServiceID=0,
            OrgFolderPath="",  # backup MIXO ma pusty – RB używa FolderPath
            Reserved1="",
            Reserved2="",
            Reserved3="",
            Reserved4="",
            ExtInfo="null",
            rb_file_id="",
            DeviceID=device_id,
            rb_LocalFolderPath="",  # RB ma None dla importowanych – zostawiamy puste
            SrcID="",
            SrcTitle="",
            SrcArtistName="",  # MIXO: NULL – RB używa ArtistID→djmdArtist.Name
            SrcAlbumName="",
            SrcLength=0,
            UUID=content_uuid,
            rb_data_status=0,  # MIXO ma 0 – 257 może blokować wyświetlanie metadanych
            rb_local_data_status=0,
            rb_local_deleted=0,
            rb_local_synced=0,
            usn=0,
            rb_local_usn=0,
            created_at=_now_dt(),
            updated_at=_now_dt(),
        )
        session.add(c)
        if len(path_to_content_id) % 2000 == 0:
            session.commit()
    session.commit()

    # contentFile – RB używa TYLKO dla plików ANLZ (waveform), nie dla ścieżek audio.
    # Backup RB: contentFile ma Path=/PIONEER/USBANLZ/... (analiza), nigdy .mp3.
    # Zapis ścieżek audio do contentFile powoduje błędy Restore – pomijamy.

    # VDJ tagi → RB My Tags (djmdMyTag + djmdSongMyTag) – opcjonalnie pomijane (test: czy tagi blokują RB)
    if not skip_my_tags:
        try:
            all_tag_values: set[str] = set()
            for t in db.tracks:
                for tag in (t.tags or []):
                    if tag and tag.strip():
                        all_tag_values.add(tag.strip())
            if all_tag_values:
                vdj_parent_id = _next_id()
                parent_tag = tables.DjmdMyTag(
                    ID=vdj_parent_id,
                    Seq=999,
                    Name="VDJ Tags",
                    Attribute=0,
                    ParentID="root",
                    UUID=_generate_uuid(),
                    rb_data_status=0,
                    rb_local_data_status=0,
                    rb_local_deleted=0,
                    rb_local_synced=0,
                    usn=0,
                    rb_local_usn=0,
                    created_at=_now_dt(),
                    updated_at=_now_dt(),
                )
                session.add(parent_tag)
                session.commit()
                tag_to_id: dict[str, str] = {}
                for seq, tag_val in enumerate(sorted(all_tag_values), 1):
                    tid = _next_id()
                    tag_to_id[tag_val] = tid
                    mt = tables.DjmdMyTag(
                        ID=tid,
                        Seq=seq,
                        Name=tag_val[:255],
                        Attribute=0,
                        ParentID=vdj_parent_id,
                        UUID=_generate_uuid(),
                        rb_data_status=0,
                        rb_local_data_status=0,
                        rb_local_deleted=0,
                        rb_local_synced=0,
                        usn=0,
                        rb_local_usn=0,
                        created_at=_now_dt(),
                        updated_at=_now_dt(),
                    )
                    session.add(mt)
                session.commit()
                song_tag_count = 0
                for t in db.tracks:
                    np = normalize_path(t.path)
                    content_id = path_to_content_id.get(np)
                    if not content_id or not t.tags:
                        continue
                    for track_no, tag_val in enumerate((x for x in t.tags if x and x.strip()), 0):
                        my_tag_id = tag_to_id.get(tag_val.strip())
                        if not my_tag_id:
                            continue
                        st = tables.DjmdSongMyTag(
                            ID=_generate_uuid(),
                            MyTagID=my_tag_id,
                            ContentID=content_id,
                            TrackNo=track_no,
                            UUID=_generate_uuid(),
                            rb_data_status=0,
                            rb_local_data_status=0,
                            rb_local_deleted=0,
                            rb_local_synced=0,
                            usn=0,
                            rb_local_usn=0,
                            created_at=_now_dt(),
                            updated_at=_now_dt(),
                        )
                        session.add(st)
                        song_tag_count += 1
                        if song_tag_count % 5000 == 0:
                            session.commit()
                session.commit()
        except Exception:
            pass  # My Tags opcjonalne – szablon może nie mieć "root"


    # Wstaw djmdCue (cue points)
    for t in db.tracks:
        np = normalize_path(t.path)
        content_id = path_to_content_id.get(np)
        content_uuid = path_to_uuid.get(np)
        if not content_id or not t.cue_points:
            continue
        for cp in t.cue_points:
            cue_id = _next_id()
            # Kind: 0 = memory cue, 1-8 = hot cue
            kind = cp.num if 1 <= cp.num <= 8 else 0
            color_id = -1  # -1 = no color
            if cp.color is not None:
                # Mapowanie ARGB do RB ColorID 1-8 (uproszczone)
                r = (cp.color >> 16) & 0xFF
                g = (cp.color >> 8) & 0xFF
                b = cp.color & 0xFF
                if r > 200 and g < 100 and b < 100:
                    color_id = 2  # Red
                elif r > 200 and g > 150 and b < 100:
                    color_id = 3  # Orange
                elif r > 200 and g > 200 and b < 100:
                    color_id = 4  # Yellow
                elif r < 100 and g > 200 and b < 100:
                    color_id = 5  # Green
                elif r < 100 and g > 200 and b > 200:
                    color_id = 6  # Aqua
                elif r < 100 and g < 100 and b > 200:
                    color_id = 7  # Blue
                elif r > 150 and g < 100 and b > 150:
                    color_id = 8  # Purple
                else:
                    color_id = 1  # Pink
            cue = tables.DjmdCue(
                ID=cue_id,
                ContentID=content_id,
                InMsec=int(cp.pos * 1000),
                InFrame=int(cp.pos * 150),
                InMpegFrame=0,
                InMpegAbs=0,
                OutMsec=-1,
                OutFrame=0,
                OutMpegFrame=0,
                OutMpegAbs=0,
                Kind=kind,
                Color=color_id,
                ColorTableIndex=0,
                ActiveLoop=0,
                Comment=cp.name[:256] if cp.name else None,
                BeatLoopSize=0,
                CueMicrosec=0,
                InPointSeekInfo=0,
                OutPointSeekInfo=0,
                ContentUUID=content_uuid,
                UUID=_generate_uuid(),
                rb_data_status=0,
                rb_local_data_status=0,
                rb_local_deleted=0,
                rb_local_synced=0,
                usn=0,
                rb_local_usn=0,
                created_at=_now_dt(),
                updated_at=_now_dt(),
            )
            session.add(cue)
    session.commit()

    # djmdPlaylist: root ma ParentID="root"
    # Attribute: 0=playlista, 1=folder
    # Budujemy drzewo playlist
    playlist_id_map: dict[tuple[str, str, int], str] = {}  # (name, parent_id, seq) -> ID

    def _ensure_playlist_id(name: str, parent_id: str, is_folder: bool, seq: int) -> str:
        key = (name, parent_id, seq)
        if key in playlist_id_map:
            return playlist_id_map[key]
        pid = _next_id()
        playlist_id_map[key] = pid
        pl = tables.DjmdPlaylist(
            ID=pid,
            Seq=seq,
            Name=name,
            ImagePath="",
            Attribute=1 if is_folder else 0,
            ParentID=parent_id,
            SmartList="",
            UUID=_generate_uuid(),
            rb_data_status=0,
            rb_local_data_status=0,
            rb_local_deleted=0,
            rb_local_synced=0,
            usn=0,
            rb_local_usn=0,
            created_at=_now_dt(),
            updated_at=_now_dt(),
        )
        session.add(pl)
        return pid

    root_id = "root"

    def _add_playlists(playlists: list[Playlist], parent_id: str, count: list) -> None:
        for i, pl in enumerate(playlists):
            pid = _ensure_playlist_id(pl.name, parent_id, pl.is_folder, seq=i)
            if pl.is_folder:
                _add_playlists(pl.children, pid, count)
            else:
                for j, track_ref in enumerate(pl.track_ids):
                    # track_ref jest znormalizowany (z vdjfolders_to_playlists)
                    content_id = path_to_content_id.get(normalize_path(track_ref) if track_ref else "")
                    if not content_id:
                        continue
                    sp_id = _next_id()
                    sp = tables.DjmdSongPlaylist(
                        ID=sp_id,
                        PlaylistID=pid,
                        ContentID=content_id,
                        TrackNo=j,
                        UUID=_generate_uuid(),
                        rb_data_status=0,
                        rb_local_data_status=0,
                        rb_local_deleted=0,
                        rb_local_synced=0,
                        usn=0,
                        rb_local_usn=0,
                        created_at=_now_dt(),
                        updated_at=_now_dt(),
                    )
                    session.add(sp)
                    count[0] += 1
                    if count[0] % 5000 == 0:
                        session.commit()
        session.commit()

    _add_playlists(db.playlists, root_id, [0])

    # Aktualizuj DjmdProperty.updated_at – RB może używać do odświeżenia widoku
    try:
        now_str = _now_dt().strftime("%Y-%m-%d %H:%M:%S.000 +00:00")
        session.execute(text("UPDATE DjmdProperty SET updated_at = :t"), {"t": now_str})
    except Exception:
        pass
    session.commit()

    # Wymuś zapis na dysk (WAL checkpoint) przed odczytem pliku
    try:
        session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    except Exception:
        pass
    session.commit()
    session.close()
    if engine:
        engine.dispose()
    if rb_db:
        rb_db.engine.dispose()
        rb_db.close()

    try:
        if output_path:
            import shutil
            shutil.copy2(db_path, output_path)
            out = Path(output_path).read_bytes()
        else:
            out = Path(db_path).read_bytes()
        return out
    finally:
        os.unlink(db_path)
