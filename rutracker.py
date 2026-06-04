import logging
import re
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("rutracker")

RUTRACKER_LOGIN = "https://rutracker.org/forum/login.php"
RUTRACKER_SEARCH = "https://rutracker.org/forum/tracker.php"
RUTRACKER_DL = "https://rutracker.org/forum/dl.php"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

QUALITY_RANK = {
    "BDRemux": 6, "BluRay": 6, "Remux": 6,
    "4K": 5, "2160p": 5, "UHD": 5,
    "HDR": 5, "DV": 5, "Dolby Vision": 5,
    "1080p": 4, "WEB-DL": 3, "WEBRip": 3,
    "720p": 2,
    "HDRip": 2, "BDRip": 2, "HDTV": 2,
    "DVD": 1, "SATRip": 1, "CAMRip": 0, "TS": 0,
}


@dataclass
class TorrentResult:
    torrent_id: str
    title: str
    size_text: str
    seeds: int
    category: str = "movies"
    quality: str = ""
    magnet: str = ""
    rank: int = 0
    year: str = ""


def quality_label(title: str) -> str:
    t = title.upper()
    # Resolution
    if "2160P" in t or "4K" in t or "UHD" in t:
        res = "4K"
    elif "1080P" in t:
        res = "1080p"
    elif "720P" in t:
        res = "720p"
    else:
        res = "SD"

    # Extras
    extras = []
    if "HDR" in t or "DOLBY VISION" in t or " DV " in t:
        extras.append("HDR")
    if "REMUX" in t or "BDREMUX" in t:
        extras.append("Remux")
    elif "BLURAY" in t:
        extras.append("BluRay")
    elif "WEB-DL" in t or "WEBRIP" in t:
        extras.append("WEB")

    return f"{res} {'/'.join(extras)}" if extras else res


def quality_score(title: str) -> int:
    t = title.upper()
    score = 1

    # Resolution is the primary factor
    if "2160P" in t or "4K" in t or "UHD" in t:
        score = 50
    elif "1080P" in t:
        score = 40
    elif "720P" in t:
        score = 20
    else:
        score = 10

    # Quality bonuses (add to resolution base)
    if "REMUX" in t or "BDREMUX" in t:
        score += 3
    if "BLURAY" in t:
        score += 2
    if "HDR" in t or "DV" in t or "DOLBY VISION" in t:
        score += 2
    if "WEB-DL" in t or "WEBRIP" in t:
        score += 1

    # Penalties
    if "CAMRIP" in t or " TS " in t:
        score = 0

    return score


class RutrackerClient:
    def __init__(self):
        self._session: requests.Session | None = None
        self._logged_in = False

    def _ensure_session(self):
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT})

    def login(self) -> bool:
        self._ensure_session()
        try:
            from config import settings
            user = settings.rutracker_user
            password = settings.rutracker_pass
            if not user or not password:
                logger.error("RUTRACKER_USER or RUTRACKER_PASS not set in .env")
                return False
            resp = self._session.post(
                RUTRACKER_LOGIN,
                data={
                    "login_username": user,
                    "login_password": password,
                    "login": "Вход",
                },
                timeout=20,
            )
            self._logged_in = "Выход" in resp.text or "logout" in resp.text.lower()
            if not self._logged_in:
                logger.error("Rutracker login failed")
            return self._logged_in
        except Exception as e:
            logger.error(f"Rutracker login error: {e}")
            return False

    def search(self, query: str, min_quality: int = 40, max_quality: int = 99) -> list[TorrentResult]:
        if not self._logged_in:
            if not self.login():
                return []

        self._ensure_session()
        try:
            resp = self._session.get(RUTRACKER_SEARCH, params={"nm": query}, timeout=20)
            resp.encoding = "windows-1251"
        except Exception as e:
            logger.error(f"Rutracker search error: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select("tr.tCenter.hl-tr")
        results: list[TorrentResult] = []

        for row in rows:
            title_el = row.select_one("a.med.tLink, a.tLink")
            if not title_el:
                continue
            title = title_el.text.strip()
            href = title_el.get("href", "")
            tid_match = re.search(r"t=(\d+)", href)
            if not tid_match:
                continue

            seeds_el = row.select_one("td.row4 b")
            seeds = int(seeds_el.text.strip()) if seeds_el and seeds_el.text.strip().isdigit() else 0

            size_el = row.select_one("td.row4 a.small")
            size_text = size_el.text.strip() if size_el else ""

            q_label = quality_label(title)
            q_rank = quality_score(title)

            if q_rank < min_quality or q_rank > max_quality:
                continue

            cat_el = row.select_one("td a.gen, td.tracker-cat a")
            cat_text = (cat_el.text.strip() if cat_el else "").lower()
            category = "series" if "сериал" in cat_text else "movies"

            year_match = re.search(r'\[(\d{4})[,.\]]', title)
            year = year_match.group(1) if year_match else ""

            results.append(TorrentResult(
                torrent_id=tid_match.group(1),
                title=title,
                size_text=size_text,
                seeds=seeds,
                category=category,
                quality=q_label,
                rank=q_rank,
                year=year,
            ))

        results.sort(key=lambda r: (-r.rank, -r.seeds))
        return results

    def get_magnet(self, torrent_id: str) -> str:
        if not self._logged_in:
            if not self.login():
                return ""

        self._ensure_session()
        try:
            dl_url = f"{RUTRACKER_DL}?t={torrent_id}"
            topic_url = f"https://rutracker.org/forum/viewtopic.php?t={torrent_id}"
            self._session.get(topic_url, timeout=15)

            resp = self._session.get(
                dl_url, timeout=15, allow_redirects=False,
                headers={"Referer": topic_url},
            )
            resp.encoding = "windows-1251"

            location = resp.headers.get("Location", "")
            if location and location.startswith("magnet:"):
                return location

            magnet_match = re.search(r'(magnet:\?xt=urn:btih:[a-fA-F0-9&dn=.;%=+_-]+)', resp.text)
            if magnet_match:
                return magnet_match.group(1)

            magnet_href = re.search(r'href="(magnet:[^"]+)"', resp.text)
            if magnet_href:
                return magnet_href.group(1)

            logger.warning(f"No magnet found for torrent {torrent_id}")
            return ""
        except Exception as e:
            logger.error(f"Rutracker get_magnet error for {torrent_id}: {e}")
            return ""

    def download_torrent(self, torrent_id: str) -> bytes | None:
        if not self._logged_in:
            if not self.login():
                return None

        self._ensure_session()
        try:
            dl_url = f"{RUTRACKER_DL}?t={torrent_id}"
            topic_url = f"https://rutracker.org/forum/viewtopic.php?t={torrent_id}"
            self._session.get(topic_url, timeout=15)

            resp = self._session.get(dl_url, timeout=20, headers={"Referer": topic_url})
            if resp.status_code == 200 and len(resp.content) > 100:
                return resp.content
            logger.warning(f"Torrent download failed: status={resp.status_code}, size={len(resp.content)}")
            return None
        except Exception as e:
            logger.error(f"Rutracker download_torrent error for {torrent_id}: {e}")
            return None


rutracker = RutrackerClient()
