import logging
import sys
import trio

from typing import List
from subprocess import PIPE, STDOUT


class SSHThread(object):
    def __init__(
        self,
        username: str,
        host: str,
        key_file: str,
        end_marker: str = "--~~--END--~~--",
        name: str = "",
    ):
        self.username = username
        self.host = host
        self._key_file = key_file
        self._name = name if name else host
        self._end_marker = end_marker
        self._logger = logging.getLogger(self._name)
        self._setup_logger()

        self._process = None

    def _setup_logger(self):
        self._logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                fmt=f"{self._name}: [%(asctime)s] %(levelname)s: %(message)s",
            )
        )
        self._logger.addHandler(handler)

    async def _write_close(self):
        await self._process.stdin.send_all(f"echo {self._end_marker}\n".encode())

    async def _read(self):
        b_line = await self._process.stdout.receive_some()
        return b_line.decode()

    async def _read_all(self):
        await self._write_close()
        read = ""
        while True:
            line = await self._read()
            # caveat is end marker must be a unique string
            if (end := line.find(self._end_marker)) != -1:
                read += line[:end]
                break
            read += line
        if read:
            self._logger.info(read.rstrip("\n"))

    async def _execute(self, cmd_str: str):
        await self._process.stdin.send_all(f"echo $ {cmd_str}\n".encode())
        await self._read_all()
        await self._process.stdin.send_all(f"{cmd_str}\n".encode())
        await self._read_all()

    async def cmd(self, cmd):
        if isinstance(cmd, List):
            for cmd_part in cmd:
                await self._execute(cmd_part)
        else:
            await self._execute(cmd)

    async def connect(self):
        self._process = await trio.lowlevel.open_process(
            [
                "ssh",
                "-T",
                "-i",
                self._key_file,
                f"{self.username}@{self.host}",
                "-o",
                "StrictHostKeyChecking=no",
            ],
            stdout=PIPE,
            stdin=PIPE,
            stderr=STDOUT,
        )

        return self

    async def file_transfer(self, local_dir: str, remote_file_path: str):
        ft_process = await trio.run_process(
            [
                "scp",
                "-o",
                "StrictHostKeyChecking=no",
                "-r",
                "-i",
                f"{self._key_file}",
                f"{self.username}@{self.host}:{local_dir}",
                f"{remote_file_path}",
            ]
        )
        self._logger.info(f"File transfer ended with exit code {ft_process.returncode}")
        return ft_process.returncode

    async def tunnel(
        self, server: "SSHThread", from_port: int, to_port: int, remote_key_file: str
    ):
        await self.cmd(
            f"ssh -L {from_port}:127.0.0.1:{to_port} {server.username}@{server.host} -i {remote_key_file} "
            f"-N -f -o StrictHostKeyChecking=no"
        )
        self._logger.info(f"Tunnel to host {server.host} opened on port {from_port}")

    async def exit(self):
        await self._process.terminate()
