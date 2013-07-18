# Copyright 2013 Seafile, Inc
# Licensed under the terms of seafile-pro-license.txt.
# You are not allowed to modify or redistribute this file.
#

import os
import ccnet
from pysearpc import SearpcError
from seaf_utils import CCNET_CONF_DIR

class SeafileDomainController(object):

    def __init__(self):
        ccnet_conf_dir = os.path.normpath(os.path.expanduser(CCNET_CONF_DIR))

        pool = ccnet.ClientPool(ccnet_conf_dir)
        self.ccnet_threaded_rpc = ccnet.CcnetThreadedRpcClient(pool, req_pool=True)

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
            ret = self.ccnet_threaded_rpc.validate_emailuser(username, password)
        except:
            return False

        if ret == 0:
            return True
        else:
            return False
