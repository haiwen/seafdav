#coding: UTF-8

from easywebdav3 import easywebdav
import os
import io
import posixpath
from seaserv import seafile_api

USER = os.environ.get('SEAFILE_TEST_USERNAME', 'test@seafiletest.com')
PASSWORD = os.environ.get('SEAFILE_TEST_PASSWORD', 'test')

def get_webapi_client():
    apiclient = seafile_api.connect('http://127.0.0.1:8000', USER, PASSWORD)
    return apiclient

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
        self._dav = easywebdav.Client(self.server, port=self.port,
                                       username=self.user,
                                       password=self.password)

    def list_repos(self):
        return [e for e in self._dav.ls('/') if e.name != '/']

    def repo_listdir(self, repo, path='/'):
        repo_name = repo.get('name')
        path = posixpath.join('/', repo_name, path.lstrip('/'))
        if not path.endswith('/'):
            path += '/'
        entries = self._dav.ls(path)
        # the file entries list also contains the path iteself, we just filter it
        # out for convenience
        return [e for e in entries if e.name != path]

    def repo_mkdir(self, repo, parentdir, dirname):
        repo_name = repo.get('name')
        fullpath = posixpath.join('/', repo_name, parentdir.lstrip('/'), dirname)
        self._dav.mkdir(fullpath)

    def repo_getfile(self, repo, path):
        fobj = io.BytesIO()
        repo_name = repo.get('name')
        fullpath = posixpath.join('/', repo_name, path.lstrip('/'))
        self._dav.download(fullpath, fobj)
        return fobj.getvalue()

    def repo_uploadfile(self, repo, localpath_or_fileobj, path):
        repo_name = repo.get('name')
        fullpath = posixpath.join('/', repo_name, path.lstrip('/'))
        self._dav.upload(localpath_or_fileobj, fullpath)

    def repo_removedir(self, repo, path):
        repo_name = repo.get('name')
        fullpath = posixpath.join('/', repo_name, path.lstrip('/'))
        self._dav.rmdir(fullpath)

    def repo_removefile(self, repo, path):
        repo_name = repo.get('name')
        fullpath = posixpath.join('/', repo_name, path.lstrip('/'))
        self._dav.delete(fullpath)
