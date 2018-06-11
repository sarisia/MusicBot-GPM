import asyncio
import sqlite3
import subprocess
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from logging import getLogger

# I NEED ASYNCHRONOUS GPM LIBRARY!
allow_requests = True
from gmusicapi import Musicmanager

from .exceptions import ExtractionError

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
        # Throws exception
        self.logged_in = self.client.login(self.credential)

        self.ffprobe = self._find_ffprobe()
    
    # Just wrap blocking functions to run in other thread.
    async def update_db(self):
        return await self.loop.run_in_executor(self.tpool, partial(self._update_db))

    async def download(self, entry):
        return await self.loop.run_in_executor(self.tpool, partial(self._download, entry))

    async def search(self, args):
        return await self.loop.run_in_executor(self.tpool, partial(self._search, args))
    
    # This is a native coroutine
    async def play(self, player, trackinfo, **meta):
        return await player.playlist.add_gpm_entry(trackinfo, **meta)

    async def play_from_id(self, player, gpmid):
        trackinfo = await self.loop.run_in_executor(self.tpool, partial(self._get_trackinfo, gpmid))
        if not trackinfo:
            raise ExtractionError("Failed to get trackinfo matches given GPMID.")
            
        await player.playlist.add_gpm_entry(trackinfo)

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
        for _ in range(3):
            _, abyte = self.client.download_song(entry.gpmid)
            if abyte:
                break

        if not abyte:
            return False, None

        with open(target, "wb") as f:
            f.write(abyte)

        return True, target

    def _get_duration(self, audio_file):
        if not self.ffprobe:
            return

        target = str(audio_file)
        cmd = self.ffprobe + " -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 " + target
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, __ = proc.communicate()
        log.debug("ffprobe stdout says: {}".format(stdout.decode("utf-8")))
        
        # S**T
        # Ensure with regular expression
        return int(float(stdout.decode("utf-8").strip()))

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
            res.append(GPMTrack(item))

        return res

    def _get_trackinfo(self, gpmid):
        db = sqlite3.connect(str(self.gpm_config_dir/"track.db"))
        db.execute("CREATE TABLE IF NOT EXISTS gpm(title, artist, album, gpmid)")

        true_gpmid = gpmid.split(":")[2]
        if not true_gpmid:
            return

        cur = db.execute("SELECT * FROM gpm WHERE gpmid = ?", [true_gpmid, ])
        result = cur.fetchone()

        db.close()

        return GPMTrack(result) if result else None

    def _find_ffprobe(self):
        program = "ffprobe"

        # Original: musicbot/player.py
        def is_exe(fpath):
            found = os.path.isfile(fpath) and os.access(fpath, os.X_OK)
            if not found and sys.platform == 'win32':
                fpath = fpath + ".exe"
                found = os.path.isfile(fpath) and os.access(fpath, os.X_OK)
            return found

        fpath, __ = os.path.split(program)
        if fpath:
            if is_exe(program):
                return program
        else:
            for path in os.environ["PATH"].split(os.pathsep):
                path = path.strip('"')
                exe_file = os.path.join(path, program)
                if is_exe(exe_file):
                    return exe_file

        log.debug("Failed to get ffprobe.")
        return None
    
class GPMTrack():
    def __init__(self, item):
        self.title = item[0]
        self.artist = item[1]
        self.album = item[2]
        self.gpmid = item[3]
