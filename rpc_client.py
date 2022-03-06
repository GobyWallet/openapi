import asyncio
from pathlib import Path
from urllib.parse import urljoin
import ssl
from ssl import SSLContext
from typing import Dict, List, Optional, Any
import yaml
import aiohttp

bytes32 = bytes


def ssl_context_for_client(
    ca_cert: Path,
    ca_key: Path,
    private_cert_path: Path,
    private_key_path: Path,

):

    ssl_context = ssl._create_unverified_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=str(ca_cert))
    ssl_context.check_hostname = False
    ssl_context.load_cert_chain(certfile=str(private_cert_path), keyfile=str(private_key_path))
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    return ssl_context


class FullNodeRpcClient:
    url: str
    session: aiohttp.ClientSession
    closing_task: Optional[asyncio.Task]
    ssl_context: Optional[SSLContext]

    @classmethod
    async def create_by_chia_root_path(cls, chia_root_path):
        self = cls()
        root_path = Path(chia_root_path)
        config_path = Path(chia_root_path) / "config" / "config.yaml"
        config = yaml.safe_load(config_path.open("r", encoding="utf-8"))
        self.url = f"https://{config['self_hostname']}:{config['full_node']['rpc_port']}"
        ca_cert_path = root_path / config["private_ssl_ca"]["crt"]
        ca_key_path = root_path / config["private_ssl_ca"]["key"]
        private_cert_path = root_path / config["daemon_ssl"]["private_crt"]
        private_key_path = root_path / config["daemon_ssl"]["private_key"]
        self.session = aiohttp.ClientSession()
        self.ssl_context = ssl_context_for_client(ca_cert_path, ca_key_path, private_cert_path, private_key_path)
        self.closing_task = None
        return self
    
    @classmethod
    async def create_by_proxy_url(cls, proxy_url):
        self = cls()
        self.url = proxy_url
        self.session = aiohttp.ClientSession()
        self.ssl_context = None
        self.closing_task = None
        return self
    
    async def raw_fetch(self, path, request_json):
        async with self.session.post(urljoin(self.url, path), json=request_json, ssl_context=self.ssl_context) as response:
            res_json = await response.json()
            return res_json

    async def fetch(self, path, request_json) -> Any:
        async with self.session.post(urljoin(self.url, path), json=request_json, ssl_context=self.ssl_context) as response:
            response.raise_for_status()
            res_json = await response.json()
            if not res_json["success"]:
                raise ValueError(res_json)
            return res_json

    def close(self):
        self.closing_task = asyncio.create_task(self.session.close())

    async def await_closed(self):
        if self.closing_task is not None:
            await self.closing_task

    async def get_network_info(self):
        return await self.fetch("get_network_info", {})
    
    async def get_coin_records_by_puzzle_hash(
        self,
        puzzle_hash: bytes32,
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> List:
        d = {"puzzle_hash": puzzle_hash.hex(), "include_spent_coins": include_spent_coins}
        if start_height is not None:
            d["start_height"] = start_height
        if end_height is not None:
            d["end_height"] = end_height

        response = await self.fetch("get_coin_records_by_puzzle_hash", d)
        return response['coin_records']

    async def get_coin_records_by_puzzle_hashes(
        self,
        puzzle_hashes: List[bytes32],
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> List:
        puzzle_hashes_hex = [ph.hex() for ph in puzzle_hashes]
        d = {"puzzle_hashes": puzzle_hashes_hex, "include_spent_coins": include_spent_coins}
        if start_height is not None:
            d["start_height"] = start_height
        if end_height is not None:
            d["end_height"] = end_height

        response = await self.fetch("get_coin_records_by_puzzle_hashes", d)
        return response["coin_records"]

    async def push_tx(self, spend_bundle: dict):
        return await self.fetch("push_tx", {"spend_bundle": spend_bundle})
