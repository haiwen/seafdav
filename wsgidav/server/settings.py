import os
import ConfigParser
from wsgidav.addons.seafile.domain_controller import SeafileDomainController
from wsgidav.addons.seafile.seafile_dav_provider import SeafileProvider

domaincontroller = SeafileDomainController()

acceptbasic = True
acceptdigest = False
defaultdigest = False

share_name = '/'
# haiwen
#   - conf
#     - seafdav.conf
#   - seafile-pro-server-1.8.0
#     - pro
#       - python
#         - seafdav
#         - WsgiDAV.egg
#           - wsgidav
#             - server
#               - seafdav_settings.py

##### a sample seafdav.conf, we only care: "share_name"
# [WEBDAV]
# enabled = true
# port = 8080
# share_name = /seafdav
##### a sample seafdav.conf

def load_seafdav_conf():
    global share_name

    seafdav_conf = os.environ['SEAFDAV_CONF']
    if not os.path.exists(seafdav_conf):
        return

    config = ConfigParser.ConfigParser()
    config.read(seafdav_conf)
    section_name = 'WEBDAV'

    if config.has_option(section_name, 'share_name'):
        share_name = config.get(section_name, 'share_name')


try:
    load_seafdav_conf()
except:
    pass

provider_mapping = {}
provider_mapping[share_name] = SeafileProvider()
