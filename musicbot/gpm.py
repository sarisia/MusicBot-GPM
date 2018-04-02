import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from logging import getLogger

# I NEED ASYNCHRONOUS GPM LIBRARY!
allow_requests = True
from gmusicapi import Musicmanager

log = getLogger(__name__)

class GPMClient():
    def __init__(self, loop):
        self.loop = loop
        self.tpool = ThreadPoolExecutor(max_workers=2)
        self.client = Musicmanager(debug_logging=False)
        self.bot_dir = Path.cwd()
        self.dl_dir = self.bot_dir/"audio_cache"
        self.gpm_config_dir = self.bot_dir/"config"/"gpm"

        self.gpm_config_dir.mkdir(exist_ok=True)

        self.credential = None
        if (self.gpm_config_dir/"credential").is_file():
            self.credential = str(self.gpm_config_dir/"credential")

        self.logged_in = False
        self.logged_in = self.client.login(self.credential)
    
    # Just wrap blocking functions to run in other thread.
    async def update_db(self):
        return await self.loop.run_in_executor(self.tpool, partial(self._update_db))

    async def download(self, entry):
        return await self.loop.run_in_executor(self.tpool, partial(self._download, entry))

    async def search(self, args):
        return await self.loop.run_in_executor(self.tpool, partial(self._search, args))
    
    # This is a native coroutine
    async def play(self, player, trackinfo, **meta):
        await player.playlist.add_gpm_entry(self, trackinfo, **meta)

    async def play_from_id(self, player, gpmid):
        trackinfo = await self.loop.run_in_executor(self.tpool, partial(self._get_trackinfo, gpmid))
        await player.playlist.add_gpm_entry(self, trackinfo)

    def _update_db(self):
        tracklist = self.client.get_uploaded_songs()
        if not tracklist:
            return None

        db = sqlite3.connect(str(self.gpm_config_dir/"track.db"))

        db.execute("DROP TABLE IF EXISTS gpm")
        db.execute("CREATE TABLE IF NOT EXISTS gpm(title, artist, album, gpmid)")
        db.executemany("INSERT INTO gpm VALUES (:title, :artist, :album, :id)", tracklist)
        db.commit()

        db.close()

        return len(tracklist)

    def _download(self, entry):
        target = self.dl_dir/entry.expected_filename
        # Let it try 3 times
        for retry in range(3):
            filename_wuse, abyte = self.client.download_song(entry.gpmid)
            if abyte:
                break

        if not abyte:
            return False, None

        with open(target, "wb") as f:
            f.write(abyte)

        return True, str(target)

    def _search(self, args):
        db = sqlite3.connect(str(self.gpm_config_dir/"track.db"))
        db.execute("CREATE TABLE IF NOT EXISTS gpm(title, artist, album, gpmid)")

        # Need better way to search DB...
        query = "%" + "%".join(args) + "%"
        cur = db.execute("SELECT * FROM gpm WHERE title||' '||artist||' '||album LIKE ?", [query, ])
        result = cur.fetchall()

        db.close()

        res = []
        for item in result:
            res.append(self.factory_trackinfo(item))

        return res

    def _get_trackinfo(self, gpmid):
        db = sqlite3.connect(str(self.gpm_config_dir/"track.db"))
        db.execute("CREATE TABLE IF NOT EXISTS gpm(title, artist, album, gpmid)")

        true_gpmid = gpmid.split(":")[2]
        if not true_gpmid:
            return

        cur = db.execute("SELECT * FROM gpm WHERE gpmid = ?", [true_gpmid, ])
        result = cur.fetchone()

        return self.factory_trackinfo(result)

    def factory_trackinfo(self, item):
        return {
            "title": item[0],
            "artist": item[1],
            "album": item[2],
            "gpmid": item[3]
        }
    