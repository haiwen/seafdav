#coding: UTF-8

import time
import os
import io
import unittest
import posixpath
import random
import string
import seafileapi
from functools import wraps
from contextlib import contextmanager
from tests.client import SeafDavClient, get_webapi_client, USER
from easywebdav.client import OperationFailed as WebDAVOperationFailed
from seaserv import seafile_api as seafilerpc

webapi = get_webapi_client()
davclient = SeafDavClient()
TEST_REPO = None

def randstring(length=20):
    return ''.join(random.choice(string.lowercase) for i in range(length))

def dav_basename(f):
    if isinstance(f, basestring):
        path = f
    else:
        path = f.name
    return posixpath.basename(path.rstrip('/'))

@contextmanager
def tmp_repo(name=None, desc=None):
    """Create a temporary repo for test before the function exectutes, and delete
    the repo after that.

    Usage:

        with tmp_repo() as repo:
            ... do things with repo ...
    """
    name = name or randstring()
    desc = desc or randstring()
    repo = webapi.repos.create_repo(name, desc)
    try:
        yield repo
    finally:
        repo.delete()

def use_tmp_repo(func):
    """Create a temporary repo for test before the function exectutes, and delete
    the repo after that.

    Typical usage:

        @use_tmp_repo
        def test_file_ops():
            repo = TEST_REPO
            ... use `repo` to do things ...
    """
    @wraps(func)
    def wrapper(*a, **kw):
        with tmp_repo() as _repo:
            global TEST_REPO
            TEST_REPO = _repo
            func(*a, **kw)
    return wrapper

class SeafDAVTestCase(unittest.TestCase):
    def test_list_repos(self):
        """Test list repos in the top level."""
        def verify_repos_count(n=None):
            entries = davclient.list_repos()
            if n is not None:
                self.assertHasLen(entries, n)
            return entries

        nrepos = len(verify_repos_count())

        with tmp_repo() as repo:
            entries = verify_repos_count(nrepos + 1)
            self.assertIn(repo.name, [dav_basename(f) for f in entries])

    def test_file_ops(self):
        """Test list/add/remove files and folders"""
        @use_tmp_repo
        def _test_under_path(path):
            repo = TEST_REPO
            path = path.rstrip('/')
            sdir = repo.get_dir('/')
            if path:
                dirs = [p for p in path.split('/') if p]
                for d in dirs:
                    sdir = sdir.mkdir(d)
            entries = davclient.repo_listdir(repo, sdir.path)
            self.assertEmpty(entries)

            # create a folder from webapi and list it in webdav
            dirname = 'folder-%s' % randstring()
            sdir.mkdir(dirname)
            entries = davclient.repo_listdir(repo, sdir.path)
            self.assertHasLen(entries, 1)
            sfolder = entries[0]
            self.assertEqual(dav_basename(sfolder), dirname)

            # create a file from webapi and list it in webdav
            testfpath = os.path.join(os.path.dirname(__file__), 'data', 'elpa.tar.gz')
            with open(testfpath, 'r') as fp:
                testfcontent = fp.read()
            fname = 'uploaded-file-%s.tgz' % randstring()
            sdir.upload_local_file(testfpath, name=fname)
            entries = davclient.repo_listdir(repo, sdir.path)
            self.assertHasLen(entries, 2)
            downloaded_file = davclient.repo_getfile(repo, posixpath.join(sdir.path, fname))
            assert downloaded_file == testfcontent

            # create a folder through webdav, and check it in webapi
            dirname = 'another-level1-folder-%s' % randstring(10)
            davclient.repo_mkdir(repo, sdir.path, dirname)
            entries = sdir.ls(force_refresh=True)
            self.assertHasLen(entries, 3)
            davdir = [e for e in entries if dav_basename(e) == dirname][0]
            self.assertEqual(dav_basename(davdir), dirname)

            # upload a file through webdav, and check it in webapi
            fname = 'uploaded-file-%s.tar.gz' % randstring()
            repo_fpath = posixpath.join(sdir.path, fname)
            davclient.repo_uploadfile(repo, testfpath, repo_fpath)
            downloaded_file = repo.get_file(repo_fpath).get_content()
            assert downloaded_file == testfcontent

            # remove a dir through webdav
            self.assertIn(dirname, [dirent.name for dirent in sdir.ls(force_refresh=True)])
            davclient.repo_removedir(repo, os.path.join(sdir.path, dirname))
            entries = sdir.ls(force_refresh=True)
            self.assertHasLen(entries, 3)
            self.assertNotIn(dirname, [dirent.name for dirent in entries])

            # remove a file through webdav
            self.assertIn(fname, [dirent.name for dirent in sdir.ls(force_refresh=True)])
            davclient.repo_removefile(repo, os.path.join(sdir.path, fname))
            entries = sdir.ls(force_refresh=True)
            self.assertHasLen(entries, 2)
            self.assertNotIn(fname, [dirent.name for dirent in entries])

        _test_under_path('/')
        _test_under_path('/level1-folder-%s' % randstring(10))
        _test_under_path('/level1-folder-%s/level2-folder-%s' %
                         (randstring(5), randstring(5)))

    def test_copy_move(self):
        """Test copy/move files and folders."""
        # XXX: python-easwebday does not support webdav COPY/MOVE operation yet.
        # with tmp_repo() as ra:
        #     with tmp_repo() as rb:
        #         roota = ra.get_dir('/')
        #         rootb = rb.get_dir('/')
        pass

    def test_repo_name_conflict(self):
        """Test the case when multiple repos have the same name"""
        repo_name = randstring(length=20)
        with tmp_repo(name=repo_name) as ra:
            with tmp_repo(name=repo_name) as rb:
                davrepos = davclient.list_repos()
                repos = [r for r in davrepos if dav_basename(r).startswith(repo_name)]
                self.assertHasLen(repos, 2)
                repos = sorted(repos, lambda x, y: cmp(x.name, y.name))
                if rb.id < ra.id:
                    rb, ra = ra, rb
                self.assertEqual(dav_basename(repos[0]), '%s-%s' % (repo_name, ra.id[:6]))
                self.assertEqual(dav_basename(repos[1]), '%s-%s' % (repo_name, rb.id[:6]))

    @use_tmp_repo
    def test_quota_check(self):
        """Assert the user storage quota should not be exceeded"""
        assert seafilerpc.set_user_quota(USER, 0) >= 0
        repo = TEST_REPO
        rootdir = repo.get_dir('/')
        testfn = 'elpa.tar.gz'
        testfpath = os.path.join(os.path.dirname(__file__), 'data', testfn)
        testfilesize = os.stat(testfpath).st_size
        rootdir.upload_local_file(testfpath)

        _wait_repo_size_recompute(repo, testfilesize)
        with _set_quota(USER, testfilesize):
            with self.assertRaises(WebDAVOperationFailed) as cm:
                davclient.repo_uploadfile(repo, testfpath, '/%s' % randstring())
            self.assertEqual(cm.exception.actual_code, 403,
                             'the operation should fail because quota is full')

            # Attempts to create empty files should also fail
            with self.assertRaises(WebDAVOperationFailed) as cm:
                empty_fileobj = io.BytesIO()
                davclient.repo_uploadfile(repo, empty_fileobj, '/%s' % randstring())
            self.assertEqual(cm.exception.actual_code, 403,
                             'the operation should fail because quota is full')

        # After the quota restored, the upload should succeed
        repo_fpath = '/%s' % randstring()
        davclient.repo_uploadfile(repo, testfpath, repo_fpath)
        with open(testfpath, 'r') as fp:
            assert fp.read() == repo.get_file(repo_fpath).get_content()

    def assertHasLen(self, obj, expected_length):
        actuallen = len(obj)
        msg = 'Expected length is %s, but actual lenght is %s' % (expected_length, actuallen)
        self.assertEqual(actuallen, expected_length, msg)

    def assertEmpty(self, obj):
        self.assertHasLen(obj, 0)

@contextmanager
def _set_quota(user, quota):
    """Set the quota of the user to the given value, and restore the old value when exit"""
    oldquota = seafilerpc.get_user_quota(user)
    if seafilerpc.set_user_quota(user, quota) < 0:
        raise RuntimeError('failed to change user quota')
    assert seafilerpc.get_user_quota(user) == quota
    try:
        yield
    finally:
        seafilerpc.set_user_quota(user, oldquota)


def _wait_repo_size_recompute(repo, size, maxretry=30):
    reposize = seafilerpc.get_repo_size(repo.id)
    retry = 0
    while reposize != size:
        if retry >= maxretry:
            assert False, 'repo size not recomputed in %s seconds' % maxretry
        retry += 1
        print 'computed = %s, expected = %s' % (reposize, size)
        time.sleep(1)
        reposize = seafilerpc.get_repo_size(repo.id)
