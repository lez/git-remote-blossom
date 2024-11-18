import sys
import asyncio
import argparse

from git_remote_blossom.util import Level, stdout_to_binary
from git_remote_blossom.cli.common import error, get_helper


async def _main():
    """
    Main entry point for git-remote-blossom Git remote helper.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "blossom_server",
        help="Full URL of a blossom server, e.g. https://blossom.nos.tr:3000")
    parser.add_argument(
        "command",
        help="'fetch' or 'push'")
    parser.add_argument(
        "command_arg", nargs="+",
        help="One or more arguments for the 'fetch' or 'push'")

    args = parser.parse_args()
    print(args)

    # configure system
    stdout_to_binary()

    blossom = args.blossom_server
    cmd = args.command
    cmd_args = args.command_arg

    helper = await get_helper(blossom, cmd, cmd_args)
    try:
        await helper.run()
    except Exception:
        if helper.verbosity >= Level.DEBUG:
            raise  # re-raise exception so it prints out a stack trace
        else:
            error('unexpected exception (run with -v for details)')
    except KeyboardInterrupt:
        # exit silently with an error code
        exit(1)

def main():
    asyncio.run(_main())
