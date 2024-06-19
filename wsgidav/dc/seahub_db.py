from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.event import contains as has_event_listener, listen as add_event_listener
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import Pool
from sqlalchemy.ext.automap import automap_base

Base = automap_base()

import wsgidav.util as util
_logger = util.get_module_logger(__name__)

def init_db_session_class():
    try:
        _logger.info('Init seahub database...')
        engine = create_seahub_db_engine()
        Base.prepare(engine, reflect=True)
        Session = sessionmaker(bind=engine)
        return Session
    except ImportError:
        return None
    except Exception as e:
        _logger.warning('Failed to init seahub db: %s.', e)
        return None

def create_seahub_db_engine():
    import seahub_settings
    db_infos = seahub_settings.DATABASES['default']
    #import local_settings
    #db_infos = local_settings.DATABASES['default']

    if db_infos.get('ENGINE') != 'django.db.backends.mysql':
        _logger.warning('Failed to init seahub db, only mysql db supported.')
        return

    db_host = db_infos.get('HOST', '127.0.0.1')
    db_port = int(db_infos.get('PORT', '3306'))
    db_name = db_infos.get('NAME')
    if not db_name:
        _logger.warning ('Failed to init seahub db, db name is not set.')
        return
    db_user = db_infos.get('USER')
    if not db_user:
        _logger.warning ('Failed to init seahub db, db user is not set.')
        return
    db_passwd = db_infos.get('PASSWORD')

    if db_passwd and not db_host.startswith('/'):
        db_url = f"mysql+pymysql://{db_user}:{quote_plus(db_passwd)}@{db_host}:{db_port}/{db_name}?charset=utf8"

    if not db_passwd and db_host.startswith('/'):
        db_url = f"mysql+pymysql://{db_user}:@localhost:{db_port}/{db_name}?unix_socket={db_host}&charset=utf8"


    # Add pool recycle, or mysql connection will be closed by mysqld if idle
    # for too long.
    kwargs = dict(pool_recycle=300, echo=False, echo_pool=False)

    engine = create_engine(db_url, **kwargs)
    if not has_event_listener(Pool, 'checkout', ping_connection):
        # We use has_event_listener to double check in case we call create_engine
        # multipe times in the same process.
        add_event_listener(Pool, 'checkout', ping_connection)

    return engine

# This is used to fix the problem of "MySQL has gone away" that happens when
# mysql server is restarted or the pooled connections are closed by the mysql
# server beacause being idle for too long.
#
# See http://stackoverflow.com/a/17791117/1467959
def ping_connection(dbapi_connection, connection_record, connection_proxy): # pylint: disable=unused-argument
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SELECT 1")
        cursor.close()
    except:
        _logger.info('fail to ping database server, disposing all cached connections')
        connection_proxy._pool.dispose() # pylint: disable=protected-access

        # Raise DisconnectionError so the pool would create a new connection
        raise DisconnectionError()
