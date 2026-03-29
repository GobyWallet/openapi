# openapi

DeFi wallet on Chia Network.

## Install

You can install Goby [here](https://chrome.google.com/webstore/detail/goby/jnkelfanjkeadonecabehalmbgpfodjm).

## Run your own node

```
git clone https://github.com/GobyWallet/openapi.git
cp settings.toml.default settings.toml
# change settings.toml

# install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# install dependencies (Python 3.12 required)
uv sync

# start api
uv run uvicorn openapi.api:app

# start watcher
uv run python -m openapi.watcher
```

## Thanks

Thanks to the contributions of [Chia Mine](https://github.com/Chia-Mine/clvm-js), MetaMask, and DeBank to crypto, we stand on your shoulders to complete this project. (🌱, 🌱)

Also, thanks to Catcoin and [Taildatabase](https://www.taildatabase.com/) for sharing the token list.

