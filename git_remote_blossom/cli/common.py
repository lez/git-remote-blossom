import aiohttp
import sys
import os

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

from monstr.encrypt import Keys

from git_remote_blossom import git
from git_remote_blossom.util import Config, stderr
from git_remote_blossom.helper import Helper


def error(msg):
    stderr(msg)
    sys.exit(1)

async def get_helper(blossom, cmd, cmd_args):
    """
    Return a Helper.
    """
    sk = None
    nsec = git.get_config_value("nostr.nsec")
    if nsec:
        if nsec.startswith("nsec1"):
            # Bech32 encoded secret key
            sk = Keys.get_key(nsec)

    helper = Helper(blossom, cmd, cmd_args, sk)
    success = await helper.connect()
    if not success:
        error('could not connect to relay')

    return helper
