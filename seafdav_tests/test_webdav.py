#coding: UTF-8

import time
import os
import io
import unittest
import posixpath
import random
import string
from functools import wraps
from contextlib import contextmanager
from client import SeafDavClient, USER, PASSWORD
from easywebdav3.easywebdav import OperationFailed as WebDAVOperationFailed
from seaserv import seafile_api as api

davclient = SeafDavClient()
TEST_REPO = None

def randstring(length=20):
    return ''.join(random.choice(string.ascii_lowercase) for i in range(length))

def dav_basename(f):
    if isinstance(f, str):
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
    repo_id = api.create_repo(name, desc, USER, enc_version=None)
    repo = {"id" : repo_id, "name" : name}
    try:
        yield repo
    finally:
        pass
        #api.remove_repo(repo_id)

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
            self.assertIn(repo.get('name'), [dav_basename(f) for f in entries])

    def test_file_ops(self):
        """Test list/add/remove files and folders"""
        @use_tmp_repo
        def _test_under_path(path):
            repo = TEST_REPO
            path = path.rstrip('/')
            #sdir = repo.get_dir('/')
            parent_dir = '/'
            if path:
                dirs = [p for p in path.split('/') if p]
                for d in dirs:
                    api.post_dir(repo.get('id'), parent_dir, d, USER)
                    parent_dir = parent_dir + d + '/'
            entries = davclient.repo_listdir(repo, path)
            self.assertEmpty(entries)

            # delete non existent folder from webapi
            dirname = 'folder-%s' % randstring()
            api.del_file(repo.get('id'), parent_dir, '[\"'+dirname+'\"]', USER)
            entries = davclient.repo_listdir(repo, parent_dir)
            self.assertEmpty(entries)

            #delete non existent file from webapi
            fname = 'uploaded-file-%s.txt' % randstring()
            api.del_file(repo.get('id'), parent_dir, '[\"'+fname+'\"]', USER)
            entries = davclient.repo_listdir(repo, parent_dir)
            self.assertEmpty(entries)

            # create a folder from webapi and list it in webdav
            dirname = 'folder-%s' % randstring()
            api.post_dir(repo.get('id'), parent_dir, dirname, USER)
        
            entries = davclient.repo_listdir(repo, parent_dir)
            self.assertHasLen(entries, 1)
            sfolder = entries[0]
            self.assertEqual(dav_basename(sfolder), dirname)
            
            # create a file from webapi and list it in webdav
            testfpath = os.path.join(os.path.dirname(__file__), 'data', 'test.txt')
            with open(testfpath, 'rb') as fp:
                testfcontent = fp.read()
            fname = 'uploaded-file-%s.txt' % randstring()
            api.post_file(repo.get('id'), testfpath, parent_dir, fname, USER)
            entries = davclient.repo_listdir(repo, parent_dir)
            self.assertHasLen(entries, 2)
            downloaded_file = davclient.repo_getfile(repo, posixpath.join(parent_dir, fname))
            assert downloaded_file == testfcontent

            # create a folder through webdav, and check it in webapi
            dirname = 'another-level1-folder-%s' % randstring(10)
            davclient.repo_mkdir(repo, parent_dir, dirname)
            entries = api.list_dir_by_path(repo.get('id'), parent_dir)
            self.assertHasLen(entries, 3)
            davdir = [e for e in entries if e.obj_name == dirname][0]
            self.assertEqual(davdir.obj_name, dirname)

            # create a existent folder through webdav
            davclient.repo_mkdir(repo, parent_dir, dirname, True)
            entries = api.list_dir_by_path(repo.get('id'), parent_dir)
            self.assertHasLen(entries, 3)

            # upload a file through webdav, and check it in webapi
            fname = 'uploaded-file-%s' % randstring()
            repo_fpath = posixpath.join(parent_dir, fname)
            davclient.repo_uploadfile(repo, testfpath, repo_fpath)
            entries = api.list_dir_by_path(repo.get('id'), parent_dir)
            self.assertHasLen(entries, 4)

            # upload a existent file through webdav
            repo_fpath = posixpath.join(parent_dir, fname)
            davclient.repo_uploadfile(repo, testfpath, repo_fpath)
            entries = api.list_dir_by_path(repo.get('id'), parent_dir)
            self.assertHasLen(entries, 4)

            # remove a dir through webdav
            self.assertIn(dirname, [dirent.obj_name for dirent in \
                                    api.list_dir_by_path(repo.get('id'), parent_dir)])
            davclient.repo_removedir(repo, os.path.join(parent_dir, dirname))
            entries = api.list_dir_by_path(repo.get('id'), parent_dir)
            self.assertHasLen(entries, 3)
            self.assertNotIn(dirname, [dirent.obj_name for dirent in entries])
            
            # remove a file through webdav
            self.assertIn(fname, [dirent.obj_name for dirent in \
                                  api.list_dir_by_path(repo.get('id'), parent_dir)])
            davclient.repo_removefile(repo, os.path.join(parent_dir, fname))
            entries = api.list_dir_by_path(repo.get('id'), parent_dir)
            self.assertHasLen(entries, 2)
            self.assertNotIn(fname, [dirent.obj_name for dirent in entries])
            
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
                repos = sorted(repos, key = lambda x: x.name)
                if rb.get('id') < ra.get('id'):
                    rb, ra = ra, rb
                self.assertEqual(dav_basename(repos[0]), '%s-%s' % (repo_name, ra.get('id')[:6]))
                self.assertEqual(dav_basename(repos[1]), '%s-%s' % (repo_name, rb.get('id')[:6]))

    @use_tmp_repo
    def test_quota_check(self):
        """Assert the user storage quota should not be exceeded"""
        assert api.set_user_quota(USER, 0) >= 0
        repo = TEST_REPO
        testfn = 'test.txt'
        testfpath = os.path.join(os.path.dirname(__file__), 'data', testfn)
        testfilesize = os.stat(testfpath).st_size
        api.post_file(repo.get('id'), testfpath, '/', '%s' % randstring(), USER)

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
        with open(testfpath, 'rb') as fp:
            assert fp.read() == davclient.repo_getfile(repo, repo_fpath)

    def assertHasLen(self, obj, expected_length):
        actuallen = len(obj)
        msg = 'Expected length is %s, but actual lenght is %s' % (expected_length, actuallen)
        self.assertEqual(actuallen, expected_length, msg)

    def assertEmpty(self, obj):
        self.assertHasLen(obj, 0)

@contextmanager
def _set_quota(user, quota):
    """Set the quota of the user to the given value, and restore the old value when exit"""
    oldquota = api.get_user_quota(user)
    if api.set_user_quota(user, quota) < 0:
        raise RuntimeError('failed to change user quota')
    assert api.get_user_quota(user) == quota
    try:
        yield
    finally:
        api.set_user_quota(user, oldquota)


def _wait_repo_size_recompute(repo, size, maxretry=30):
    reposize = api.get_repo_size(repo.get('id'))
    retry = 0
    while reposize != size:
        if retry >= maxretry:
            assert False, 'repo size not recomputed in %s seconds' % maxretry
        retry += 1
        print('computed = %s, expected = %s' % (reposize, size))
        time.sleep(1)
        reposize = api.get_repo_size(repo.get('id'))
