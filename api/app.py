from nose.tools import set_trace
import os
import logging
import urlparse

import flask
from flask import (
    Flask, 
    Response,
    redirect,
)
from flask_sqlalchemy_session import flask_scoped_session
from config import Configuration
from core.model import SessionManager

app = Flask(__name__)

testing = 'TESTING' in os.environ
db_url = Configuration.database_url(testing)
SessionManager.initialize(db_url)
session_factory = SessionManager.sessionmaker(db_url)
_db = flask_scoped_session(session_factory, app)
SessionManager.initialize_data(_db)

import routes
if Configuration.get(Configuration.INCLUDE_ADMIN_INTERFACE):
    import admin.routes

debug = Configuration.logging_policy().get("level") == 'DEBUG'
logging.getLogger().info("Application debug mode==%r" % debug)
app.config['DEBUG'] = debug
app.debug = debug



def run():
    debug = True
    url = Configuration.integration_url(
        Configuration.CIRCULATION_MANAGER_INTEGRATION, required=True)
    scheme, netloc, path, parameters, query, fragment = urlparse.urlparse(url)
    if ':' in netloc:
        host, port = netloc.split(':')
        port = int(port)
    else:
        host = netloc
        port = 80

    # Workaround for a "Resource temporarily unavailable" error when
    # running in debug mode with the global socket timeout set by isbnlib
    if debug:
        import socket
        socket.setdefaulttimeout(None)

    logging.info("Starting app on %s:%s", host, port)
    app.run(debug=debug, host=host, port=port)


