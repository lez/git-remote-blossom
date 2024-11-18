import os
import sys
import json
import time
import asyncio
from datetime import datetime

from monstr.encrypt import Keys
from monstr.event.event import Event
from monstr.client.client import Client

from git_remote_blossom import git
from git_remote_blossom.util import stderr, Level


STATE_KIND = 30618

class GitRemoteError(Exception):
    pass


class GitRemote:
    def __init__(self, sk, verbosity):
        self._sk = sk
        self._state_event = None
        self._remote_pubkey = sk.public_key_hex()  # for push
        self._git_dir = os.environ['GIT_DIR']
        self._verbosity = verbosity
        self._objectformat = git.get_config_value("extensions.objectformat") or "sha1"

    async def connect(self):
        #WE_ARE_HERE: Find k:30617 repo announcement event on self._relay.
        # If exists, use relays and blossoms from that event instead.
        pass

    async def get_refs(self, for_push):
        """
        Return (first_push, refs) tuple.
        Returned `first_push` indicates the repo is nonexistent yet.
        Returned `refs` dict contains refs present on the remote.
            Its keys are refnames,
            values are tuple of (sha1, blossom_key).
        """
        if self._state_event is None:
            await self._fetch_state_event()

        if self._state_event is None:
            if not for_push:
                return False, {}
            else:
                return True, {}

        refs = {}
        for t in self._state_event.tags:
            if t[0] == "ref":
                refname = "refs/" + t[1]
                sha = t[2]
                refs[refname] = (sha, t[3])

        return False, refs

    async def _fetch_state_event(self):
        try:
            async with Client(self._relay) as c:
                evs = await c.query({
                    "kinds": [STATE_KIND],
                    "authors": [self._remote_pubkey],
                    "#d": [self._repo]
                })
                if len(evs) == 0:
                    self._trace(
                        f"Git repo state event not found on relay [{self._relay}].",
                        level=Level.INFO)
                    return

                assert len(evs) == 1, evs
                self._state_event = evs[0]

        except ConnectionError as e:
            self._trace(f"Cannot connect to relay [{self._relay}]: {str(e)}", level=Level.INFO)
            raise SystemExit(1)

    async def _publish_state_event(self):
        self._trace("STATE EVENT", level=Level.INFO)
        self._trace(self._state_event.tags.tags, level=Level.INFO)
        # created_at is converted to datetime.datetime in setter.
        old_created_at = self._state_event.created_at
        self._state_event.created_at = int(time.time())
        if old_created_at == self._state_event.created_at:
            # We need newer created_at to replace previous event.
            self._state_event.created_at = int(time.time()) + 1

        self._state_event.sign(self._sk.private_key_hex())

        async with Client(self._relay) as c:
            c.publish(self._state_event)
            await asyncio.sleep(1)
            #FIXME: make publish() wait for the relay's response.

    def get_ref(self, ref):
        assert self._state_event, "No state event"

        for t in self._state_event.tags:
            if t[0] == "ref" and t[1] == ref[5:]:
                self._write_blossom_key(t[2], bytes.fromhex(t[3]))
                return t[2]

        return None

    def set_ref(self, ref, sha):
        assert ref.startswith("refs/"), ref

        blossom_key = self._read_blossom_key(sha)

        for t in self._state_event.tags:
            if t[0] == "ref" and t[1] == ref[5:]:
                t[2] = sha
                t[3] = blossom_key.hex()
                return

        self._state_event.tags.tags.append(["ref", ref[5:], sha, blossom_key.hex()])

    def set_symref(self, symref, ref):
        for t in self._state_event.tags:
            if t[0] == "symref" and t[1] == symref:
                t[2] = f"ref: {ref}"
                return

        self._state_event.tags.tags.append(["symref", symref, f"ref: {ref}"])

    async def write_ref(self, new_sha, dst, force=False):
        """
        Update the given reference to point to the given object.

        Return None if there is no error, otherwise return a description of the
        error.
        """
        assert dst.startswith("refs/"), dst
        self._trace(f"write_ref(new_sha={new_sha}, dst={dst}, force={force})")

        if self._state_event is None:
            await self._fetch_state_event()
        if self._state_event is None:
            self._create_state_event()

        if not force:
            sha = self.get_ref(dst)
            if sha:
                if not git.object_exists(sha):
                    return 'fetch first'
                is_fast_forward = git.is_ancestor(sha, new_sha)
                if not is_fast_forward:
                    return 'non-fast-forward'

        self.set_ref(dst, new_sha)

        await self._publish_state_event()

    def _create_state_event(self):
        self._state_event = Event(
            pub_key=self._sk.public_key_hex(),
            tags=[
                ["d", self._repo],
            ],
            kind=STATE_KIND
        )

    async def write_symbolic_ref(self, name, ref):
        """Write the given symbolic ref to the remote.
        Return None if there is no error, otherwise return a description of the error.
        """
        self._trace(f"write_symbolic_ref({name}, {ref})")
        if self._state_event is None:
            await self._fetch_state_event()
        if self._state_event is None:
            self._create_state_event()

        self.set_symref(name, ref)
        await self._publish_state_event()

    async def read_symbolic_ref(self, path):
        """
        Return the content of a given symbolic ref on the remote,
        or None if the symbolic ref does not exist.
        """
        assert path == "HEAD", path
        if self._state_event is None:
            await self._fetch_state_event()

        for t in self._state_event.tags:
            if t[0] == "symref" and t[1] == path:
                assert t[2].startswith("ref: ")
                return t[2][5:]

        return None

    def _trace(self, message, level=Level.DEBUG, exact=False):
        """
        Log a message with a given severity level.
        """
        if level > self._verbosity:
            return

        if exact:
            if level == self._verbosity:
                stderr(message)
            return

        if level <= Level.ERROR:
            stderr('error: %s\n' % message)
        elif level == Level.INFO:
            stderr('info: %s\n' % message)
        elif level >= Level.DEBUG:
            stderr('debug: %s\n' % message)

    def _blossom_path(self, sha):
        # sha is in hex
        prefix = sha[:2]
        suffix = sha[2:]
        return os.path.join(self._git_dir, "blossom", prefix, suffix)

    def _read_blossom_key(self, sha):
        # Takes hex sha1, returns binary sha256
        path = self._blossom_path(sha)
        if not os.path.exists(path):
            return None
        return open(path, "rb").read()

    def _write_blossom_key(self, sha, blossom_key):
        path = self._blossom_path(sha)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(blossom_key)
        os.rename(path + ".tmp", path)
