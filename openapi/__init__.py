import os
import logging
import logzero


cwd = os.path.dirname(__file__)

log_dir = os.path.join(cwd, "../", "logs")

if not os.path.exists(log_dir):
    os.mkdir(log_dir)

from .config import LOG_LEVEL

logger = logzero.setup_logger(
    __name__, level=logging.getLevelName(LOG_LEVEL), logfile=os.path.join(log_dir, "api.log"),
    disableStderrLogger=True)