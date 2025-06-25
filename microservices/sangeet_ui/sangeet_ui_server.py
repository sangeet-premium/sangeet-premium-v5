from flask import (
    Flask
)
import os
import secrets

from ytmusicapi import YTMusic

from database import database # For init_postgres_db




def operation_main():
    database.init_postgres_db()

# Initialize the database immediately
operation_main()

from interconnect.config import config
from functools import wraps

import psycopg2
from database.database import get_pg_connection
from datetime import timedelta


from routes import sangeet_all , settings , sangeet_home ,  auth , cdn , download_server_proxy , thumbnail_server

from logger.log import setup_logger as log
server = Flask("sangeet_ui_server_main")


server.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365) # Make sessions last for one year
# Register all blueprints
server.register_blueprint(cdn.bp)
server.register_blueprint(auth.bp)
server.register_blueprint(sangeet_all.bp)
server.register_blueprint(download_server_proxy.bp)
server.register_blueprint(sangeet_home.server)
server.register_blueprint(thumbnail_server.bp)
server.register_blueprint(settings.settings_bp)

# Initialize ytmusic
ytmusic = YTMusic()

logger = log(__name__)


env_data_01 = config.get_env_data(os.path.join(os.getcwd() , "configs" , "ui" , "config.conf"))

# Securely load secret key
try:
    with open("key.txt" , "r") as md:
        key = md.read().strip()
    if not key:
        logger.warning("key.txt is empty. Generating a new secret key.")
        key = secrets.token_hex(32)
        with open("key.txt", "w") as md_write:
            md_write.write(key)
    server.secret_key = key
except FileNotFoundError:
    logger.warning("key.txt not found. Generating a new secret key and saving to key.txt.")
    key = secrets.token_hex(32)
    try:
        with open("key.txt", "w") as md_write:
            md_write.write(key)
        server.secret_key = key
    except IOError as e:
        logger.error(f"Could not write key.txt: {e}. Session security will be compromised.")
        server.secret_key = secrets.token_hex(32)



if __name__ == "__main__":
   server.run(port=80, host="localhost")