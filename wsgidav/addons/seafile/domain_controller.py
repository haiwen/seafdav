import os
import ccnet
from pysearpc import SearpcError

class SeafileDomainController(object):

    def __init__(self, ccnet_conf_dir):
        self.ccnet_conf_dir = os.path.normpath(os.path.expanduser(ccnet_conf_dir))
        print "Loading ccnet config from " + self.ccnet_conf_dir

        pool = ccnet.ClientPool(self.ccnet_conf_dir)
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
        try:
            ret = self.ccnet_threaded_rpc.validate_emailuser(username, password)
        except:
            return False

        if ret == 0:
            return True
        else:
            return False
