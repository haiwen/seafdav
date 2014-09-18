#coding: UTF-8

import easywebdav
import os

USER = os.environ.get('SEAFILE_TEST_USERNAME', 'test@seafiletest.com')
PASSWORD = os.environ.get('SEAFILE_TEST_PASSWORD', 'testtest')

class SeafDavClient(object):
    """Wrapper around easywebdav to provide common operations on seafile webdav
    server.

    Davfs2 would be a better option, but it's not supported on travis ci.
    """
    server = '127.0.0.1'
    port = 8080
    user = USER
    password = PASSWORD

    def __init__(self):
        self._dav = easywebdav.connect(self.server, port=self.port,
                                       username=self.user,
                                       password=self.password)

    def ls(self, path=''):
        return self._dav.ls(path)
