import os
import ccnet
from pysearpc import SearpcError
from seaf_utils import CCNET_CONF_DIR, SEAFILE_CENTRAL_CONF_DIR, multi_tenancy_enabled
import wsgidav.util as util

import seahub_db
from seahub_db import Base
import seahub_settings

_logger = util.getModuleLogger(__name__)

# the block size for the cipher object; must be 16, 24, or 32 for AES
BLOCK_SIZE = 32

import base64
PADDING = '{'

# An encrypted block size must be a multiple of 16
pad = lambda s: s + (16 - len(s) % 16) * PADDING
# encrypt with AES, encode with base64
EncodeAES = lambda c, s: base64.b64encode(c.encrypt(pad(s)))

class SeafileDomainController(object):

    def __init__(self):
        pool = ccnet.ClientPool(CCNET_CONF_DIR, central_config_dir=SEAFILE_CENTRAL_CONF_DIR)
        self.ccnet_threaded_rpc = ccnet.CcnetThreadedRpcClient(pool, req_pool=True)
        self.session_cls = seahub_db.init_db_session_class()

    def __repr__(self):
        return self.__class__.__name__

    def getDomainRealm(self, inputURL, environ):
        return "Seafile Authentication"

    def requireAuthentication(self, realmname, envrion):
        return True

    def isRealmUser(self, realmname, username, environ):
        return True

    def getRealmUserPassword(self, realmname, username, environ):
        """
        Not applicable to seafile.
        """
        return ""

    def authDomainUser(self, realmname, username, password, environ):
        if "'" in username:
            return False

        try:
            ccnet_email = None
            session = self.session_cls()

            user = self.ccnet_threaded_rpc.get_emailuser(username)
            if user:
                ccnet_email = user.email
            else:
                profile_profile = Base.classes.profile_profile
                q = session.query(profile_profile.user).filter(profile_profile.contact_email==username)
                res = q.first()
                if res:
                    ccnet_email = res[0]

            if not ccnet_email:
                _logger.warning('User %s doesn\'t exist', username)
                session.close()
                return False

            if self.ccnet_threaded_rpc.validate_emailuser(ccnet_email, password) != 0:
                from Crypto.Cipher import AES
                secret = seahub_settings.SECRET_KEY[:BLOCK_SIZE]
                cipher = AES.new(secret, AES.MODE_ECB)
                encoded_str = 'aes$' + EncodeAES(cipher, password)
                options_useroptions = Base.classes.options_useroptions
                q = session.query(options_useroptions.email)
                q = q.filter(options_useroptions.email==ccnet_email,
                             options_useroptions.option_val==encoded_str)
                res = q.first()
                if not res:
                    session.close()
                    return False

            session.close()
            username = ccnet_email
        except Exception as e:
            _logger.warning('Failed to login: %s', e)
            return False

        try:
            user = self.ccnet_threaded_rpc.get_emailuser_with_import(username)
            if user.role == 'guest':
                environ['seafile.is_guest'] = True
            else:
                environ['seafile.is_guest'] = False
        except Exception as e:
            _logger.exception('get_emailuser')

        if multi_tenancy_enabled():
            try:
                orgs = self.ccnet_threaded_rpc.get_orgs_by_user(username)
                if orgs:
                    environ['seafile.org_id'] = orgs[0].org_id
            except Exception, e:
                _logger.exception('get_orgs_by_user')
                pass

        environ["http_authenticator.username"] = username.encode('utf8')

        return True
