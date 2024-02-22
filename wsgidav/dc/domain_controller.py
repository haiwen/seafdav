import os
import posixpath
import seahub_settings
from seaserv import ccnet_api as api
from pysearpc import SearpcError
from wsgidav.dc.seaf_utils import CCNET_CONF_DIR, SEAFILE_CENTRAL_CONF_DIR, multi_tenancy_enabled
from wsgidav.dc import seahub_db
import wsgidav.util as util
from wsgidav.dc.base_dc import BaseDomainController
from sqlalchemy.sql import exists
# basic_auth_user, get_domain_realm, require_authentication
_logger = util.get_module_logger(__name__)

# the block size for the cipher object; must be 16, 24, or 32 for AES
BLOCK_SIZE = 32

import base64
PADDING = b'{'

# An encrypted block size must be a multiple of 16
pad = lambda s: s + (16 - len(s) % 16) * PADDING
# encrypt with AES, encode with base64
EncodeAES = lambda c, s: base64.b64encode(c.encrypt(pad(s)))

class SeafileDomainController(BaseDomainController):

    def __init__(self, wsgidav_app, config):
        self.session_cls = seahub_db.init_db_session_class()

    def __repr__(self):
        return self.__class__.__name__

    def supports_http_digest_auth(self):
        # We have access to a plaintext password (or stored hash)
        return True

    def get_domain_realm(self, inputURL, environ):
        return "Seafile Authentication"

    def require_authentication(self, realmname, envrion):
        return True

    def isRealmUser(self, realmname, username, environ):
        return True

    def getRealmUserPassword(self, realmname, username, environ):
        """
        Not applicable to seafile.
        """
        return ""

    def basic_auth_user(self, realmname, username, password, environ):
        if "'" in username:
            return False

        try:
            ccnet_email = None
            session = None
            if self.session_cls:
                session = self.session_cls()

            user = api.get_emailuser(username)
            if user:
                ccnet_email = user.email
            else:
                if session:
                    profile_profile = seahub_db.Base.classes.profile_profile
                    q = session.query(profile_profile.user).filter(profile_profile.contact_email==username)
                    res = q.first()
                    if res:
                        ccnet_email = res[0]

            if not ccnet_email:
                _logger.warning('User %s doesn\'t exist', username)
                return False
            
            enable_webdav_secret = False
            if hasattr(seahub_settings, 'ENABLE_WEBDAV_SECRET'):
                enable_webdav_secret = seahub_settings.ENABLE_WEBDAV_SECRET
            
            enable_two_factor_auth = False
            if session and enableTwoFactorAuth(session, ccnet_email):
                enable_two_factor_auth = True
            
            if not enable_webdav_secret and enable_two_factor_auth:
                _logger.warning("Two factor auth is enabled, no access to webdav.")
                return False
            elif enable_webdav_secret and enable_two_factor_auth:
                if not validateSecret(session, password, ccnet_email):
                    return False
            elif not enable_webdav_secret and not enable_two_factor_auth:
                if api.validate_emailuser(ccnet_email, password) != 0:
                    return False
            else:
                if not validateSecret(session, password, ccnet_email) and \
                api.validate_emailuser(ccnet_email, password) != 0:
                    return False

            username = ccnet_email
        except Exception as e:
            _logger.warning('Failed to login: %s', e)
            return False
        finally:
            if session:
                session.close()

        try:
            user = api.get_emailuser_with_import(username)
            if user.role == 'guest':
                environ['seafile.is_guest'] = True
            else:
                environ['seafile.is_guest'] = False
        except Exception as e:
            _logger.exception('get_emailuser')

        if multi_tenancy_enabled():
            try:
                orgs = api.get_orgs_by_user(username)
                if orgs:
                    environ['seafile.org_id'] = orgs[0].org_id
            except Exception as e:
                _logger.exception('get_orgs_by_user')
                pass

        environ["http_authenticator.username"] = username

        return True

def validateSecret(session, password, ccnet_email):
    if not session:
        return False
    from Crypto.Cipher import AES
    secret = seahub_settings.SECRET_KEY[:BLOCK_SIZE]
    cipher = AES.new(secret.encode('utf8'), AES.MODE_ECB)
    encoded_str = 'aes$' + EncodeAES(cipher, password.encode('utf8')).decode('utf8')
    options_useroptions = seahub_db.Base.classes.options_useroptions
    q = session.query(options_useroptions.email)
    q = q.filter(options_useroptions.email==ccnet_email,
                    options_useroptions.option_val==encoded_str)
    res = q.first()
    if not res:
        return False
    return True

def enableTwoFactorAuth(session, email):
    enable_settings_via_web = True
    if hasattr(seahub_settings, 'ENABLE_SETTINGS_VIA_WEB'):
        enable_settings_via_web = seahub_settings.ENABLE_SETTINGS_VIA_WEB

    global_two_factor_auth = False
    if enable_settings_via_web:
        constance_config = seahub_db.Base.classes.constance_config
        q = session.query(constance_config.value).filter(constance_config.constance_key=='ENABLE_TWO_FACTOR_AUTH')
        res = q.first()
        if res:
            if res[0] == 'gAJLAS4=':
                global_two_factor_auth = True
            else:
                return False
    elif hasattr(seahub_settings, 'ENABLE_TWO_FACTOR_AUTH'):
        global_two_factor_auth = seahub_settings.ENABLE_TWO_FACTOR_AUTH

    if global_two_factor_auth:
        two_factor_staticdevice = seahub_db.Base.classes.two_factor_staticdevice
        two_factor_totpdevice = seahub_db.Base.classes.two_factor_totpdevice
        if session.query(exists().where(two_factor_staticdevice.user==email)).scalar() \
            or session.query(exists().where(two_factor_totpdevice.user==email)).scalar():
            return True

    return False
