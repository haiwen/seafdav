# -*- coding: iso-8859-1 -*-
"""
run_server
==========

:Author: Ho Chun Wei, fuzzybr80(at)gmail.com (author of original PyFileServer)
:Author: Martin Wendt, moogle(at)wwwendt.de 
:Author: Jonathan Xu, xjqkilling@gmail.com (clean up for Seafile's use)
:Copyright: Licensed under the MIT license, see LICENSE file in this package.

Standalone server that runs WsgiDAV.

These tasks are performed:

    - Set up the configuration from defaults, config file and command line options.
    - Instantiate the WsgiDAVApp object (which is a WSGI application)
    - Start a WSGI server for this WsgiDAVApp object   

Configuration is defined like this:

    1. Set reasonable default settings. 
    2. Get config file path from SEAFDAV_CONF environment variable.
       From this config file we'll webdav share_name.
    3. If command line options are passed, use them to override settings:
    
       ``--host`` option overrides ``hostname`` setting.
         
       ``--port`` option overrides ``port`` setting.  
"""

from optparse import OptionParser
from pprint import pprint
from inspect import isfunction
from wsgidav.wsgidav_app import DEFAULT_CONFIG
import atexit
import logging
import traceback
import sys
import os
from wsgidav.xml_tools import useLxml
from wsgidav import util

try:
    from wsgidav.version import __version__
    from wsgidav.wsgidav_app import WsgiDAVApp
except ImportError, e:
    raise RuntimeError("Could not import wsgidav package:\n%s\nSee https://github.com/mar10/wsgidav/." % e)

import ConfigParser
from wsgidav.addons.seafile.domain_controller import SeafileDomainController
from wsgidav.addons.seafile.seafile_dav_provider import SeafileProvider

__docformat__ = "reStructuredText"

PYTHON_VERSION = "%s.%s.%s" % (sys.version_info[0], sys.version_info[1], sys.version_info[2])


def _get_checked_path(path, mustExist=True, allowNone=True):
    """Convert path to absolute if not None."""
    if path in (None, ""):
        if allowNone:
            return None
        else:
            raise ValueError("Invalid path %r" % path)
    path = os.path.abspath(path)
    if mustExist and not os.path.exists(path):
        raise ValueError("Invalid path %r" % path)
    return path

def _initCommandLineOptions():
    """Parse command line options into a dictionary."""
    
    parser = OptionParser(usage='%prog [runfcgi] [options]', 
                          version=__version__,
#                          conflict_handler="error",
                          description=None, #description,
                          add_help_option=True,
                          prog="wsgidav",
#                          epilog=epilog # TODO: Not available on Python 2.4?
                          )    
 
    parser.add_option("-p", "--port", 
                      dest="port",
                      type="int",
                      # default=8080,
                      help="port to serve on (default: %default)")
    parser.add_option("-H", "--host", # '-h' conflicts with --help  
                      dest="host",
                      # default="localhost",
                      help="host to serve from (default: %default). 'localhost' is only accessible from the local computer. Use 0.0.0.0 to make your application public"),

    parser.add_option("-q", "--quiet",
                      action="store_const", const=0, dest="verbose",
                      help="suppress any output except for errors.")
    parser.add_option("-v", "--verbose",
                      action="store_const", const=2, dest="verbose",# default=1,
                      help="Set verbose = 2: print informational output.")
    parser.add_option("-d", "--debug",
                      action="store_const", const=3, dest="verbose",
                      help="Set verbose = 3: print requests and responses.")

    parser.add_option("-l", "--log-file",
                      dest="log_path",
                      help="Log file path.")

    parser.add_option("", "--pid",
                      dest="pid_file",
                      help="PID file path")

   
    (options, args) = parser.parse_args()

    if len(args) > 1:
        parser.error("Too many arguments")

    # Convert options object to dictionary
    cmdLineOpts = options.__dict__.copy()
    if options.verbose >= 3:
        print "Command line options:"
        for k, v in cmdLineOpts.items():
            print "    %-12s: %s" % (k, v)
    return cmdLineOpts, args

def _loadSeafileSettings(config):
    # Seafile cannot support digest auth, since plain text password is needed.
    config['acceptbasic'] = True
    config['acceptdigest'] = False
    config['defaultdigest'] = False

    # Use Seafile authenticator
    config['domaincontroller'] = SeafileDomainController()

    # Load share_name from seafdav config file

    # haiwen
    #   - conf
    #     - seafdav.conf

    ##### a sample seafdav.conf, we only care: "share_name"
    # [WEBDAV]
    # enabled = true
    # port = 8080
    # share_name = /seafdav
    ##### a sample seafdav.conf

    share_name = '/'

    seafdav_conf = os.environ.get('SEAFDAV_CONF')
    if seafdav_conf and os.path.exists(seafdav_conf):
        cp = ConfigParser.ConfigParser()
        cp.read(seafdav_conf)
        section_name = 'WEBDAV'

        if cp.has_option(section_name, 'share_name'):
            share_name = cp.get(section_name, 'share_name')

    # Setup provider mapping for Seafile. E.g. /seafdav -> seafile provider.
    provider_mapping = {}
    provider_mapping[share_name] = SeafileProvider()
    config['provider_mapping'] = provider_mapping

def _initConfig():
    """Setup configuration dictionary from default, command line and configuration file."""
    cmdLineOpts, args = _initCommandLineOptions()

    # Set config defaults
    config = DEFAULT_CONFIG.copy()
    if cmdLineOpts["verbose"] is None:
        temp_verbose = config["verbose"]
    else:
        temp_verbose = cmdLineOpts["verbose"]

    _loadSeafileSettings(config)
    
    # Command line options
    if cmdLineOpts.get("port"):
        config["port"] = cmdLineOpts.get("port")
    if cmdLineOpts.get("host"):
        config["host"] = cmdLineOpts.get("host")
    if cmdLineOpts.get("verbose") is not None:
        config["verbose"] = cmdLineOpts.get("verbose")

    log_path = cmdLineOpts.get("log_path", "")
    if log_path:
        log_path = os.path.abspath(log_path)
        config["log_path"] = log_path

    pid_file = cmdLineOpts.get("pid_file", "")
    if pid_file:
        pid_file = os.path.abspath(pid_file)
        config["pid_file"] = pid_file

    if not config["provider_mapping"]:
        print >>sys.stderr, "ERROR: No DAV provider defined. Try --help option."
        sys.exit(-1)

    return config, args

def _runCherryPy(app, config, mode):
    """Run WsgiDAV using cherrypy.wsgiserver, if CherryPy is installed."""
    assert mode in ("cherrypy", "cherrypy-bundled")

    try:
        if mode == "cherrypy-bundled":
            # Need to set import root folder
            server_folder = os.path.dirname(__file__)
            sys.path.append(server_folder)
            from cherrypy import wsgiserver
            from cherrypy.wsgiserver.ssl_builtin import BuiltinSSLAdapter
        else:
            # http://cherrypy.org/apidocs/3.0.2/cherrypy.wsgiserver-module.html  
            from cherrypy import wsgiserver, __version__ as cp_version, BuiltinSSLAdapter

        version = "WsgiDAV/%s %s Python/%s" % (
            __version__, 
            wsgiserver.CherryPyWSGIServer.version, 
            PYTHON_VERSION)
        wsgiserver.CherryPyWSGIServer.version = version

        # Support SSL
        ssl_certificate = _get_checked_path(config.get("ssl_certificate"))
        ssl_private_key = _get_checked_path(config.get("ssl_private_key"))
        ssl_certificate_chain = _get_checked_path(config.get("ssl_certificate_chain"))
        protocol = "http"
        if ssl_certificate:
            assert ssl_private_key
            wsgiserver.CherryPyWSGIServer.ssl_adapter = BuiltinSSLAdapter(ssl_certificate, ssl_private_key, ssl_certificate_chain)
            protocol = "https"
            if config["verbose"] >= 1:
                print("SSL / HTTPS enabled.")

        if config["verbose"] >= 1:
            print "Running %s" % version
            print("Listening on %s://%s:%s ..." % (protocol, config["host"], config["port"]))
        server = wsgiserver.CherryPyWSGIServer(
            (config["host"], config["port"]), 
            app,
            server_name=version,
            )

        try:
            server.start()
        except KeyboardInterrupt:
            if config["verbose"] >= 1:
                print "Caught Ctrl-C, shutting down..."
            server.stop()
    except ImportError, e:
        if config["verbose"] >= 1:
            print "Could not import wsgiserver.CherryPyWSGIServer."
        return False
    return True

def _runFlup(app, config, mode):
    """Run WsgiDAV using flup.server.fcgi, if Flup is installed."""
    try:
        # http://trac.saddi.com/flup/wiki/FlupServers
        if mode == "flup-fcgi" or "runfcgi":
            from flup.server.fcgi import WSGIServer, __version__ as flupver
        elif mode == "flup-fcgi_fork":
            from flup.server.fcgi_fork import WSGIServer, __version__ as flupver
        else:
            raise ValueError    

        if config["verbose"] >= 2:
            print "Running WsgiDAV/%s %s/%s..." % (__version__,
                                                   WSGIServer.__module__,
                                                   flupver)
        server = WSGIServer(app,
                            bindAddress=(config["host"], config["port"]),
#                            bindAddress=("127.0.0.1", 8001),
#                            debug=True,
                            )
        server.run()
    except ImportError, e:
        if config["verbose"] >= 1:
            print "Could not import flup.server.fcgi", e
        return False
    return True

def write_pidfile(pidfile):
    pid = os.getpid()
    with open(pidfile, 'w') as fp:
        fp.write(str(pid))

    def remove_pidfile():
        '''Remove the pidfile when exit'''
        logging.info('remove pidfile %s' % pidfile)
        try:
            os.remove(pidfile)
        except:
            pass

    atexit.register(remove_pidfile)

def run():
    config, args = _initConfig()
    
    app = WsgiDAVApp(config)
    
    pid_file_name = config.get("pid_file", "")
    if pid_file_name:
        write_pidfile(pid_file_name)

    if len(args) > 0 and args[0] == 'runfcgi':
        _runFlup(app, config, 'flup-fcgi_fork')
    else:
        _runCherryPy(app, config, 'cherrypy-bundled')
    
if __name__ == "__main__":
    run()
