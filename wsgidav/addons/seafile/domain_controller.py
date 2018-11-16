import os
import ccnet
from pysearpc import SearpcError
from seaf_utils import CCNET_CONF_DIR, SEAFILE_CENTRAL_CONF_DIR, multi_tenancy_enabled
import wsgidav.util as util

import seahub_db
from seahub_db import Base

_logger = util.getModuleLogger(__name__)

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
            if self.ccnet_threaded_rpc.validate_emailuser(username, password) != 0:
                if not self.session_cls:
                    return False
                # Assume that @username is a contact_email, get real email from seahub_db
                session = self.session_cls()
                profile_profile = Base.classes.profile_profile
                q = session.query(profile_profile.user).filter(profile_profile.contact_email==username)
                email = q.first()[0]
                session.close()
                if not email:
                    return False
                if self.ccnet_threaded_rpc.validate_emailuser(email, password) != 0:
                    return False

                username = email
        except Exception as e:
            print e
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

        return True
