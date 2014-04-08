# Copyright 2013 Seafile, Inc
# Licensed under the terms of seafile-pro-license.txt.
# You are not allowed to modify or redistribute this file.
#

from wsgidav.dav_error import DAVError, HTTP_BAD_REQUEST, HTTP_FORBIDDEN, \
    HTTP_NOT_FOUND, HTTP_INTERNAL_ERROR
from wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection

import wsgidav.util as util
import os
#import mimetypes
import shutil
import stat
import sys
import time
import tempfile

import seaserv
from seaserv import seafile_api
from pysearpc import SearpcError
import seafObj
from seafObj import SeafDir, SeafFile, SeafCommit, SeafBlock
from seaf_utils import SEAFILE_CONF_DIR, UTF8Dict, utf8_path_join

__docformat__ = "reStructuredText"

_logger = util.getModuleLogger(__name__)

NEED_PROGRESS = 0

class SeafileStream(object):
    """
    Implements basic file-like interface.
    """
    def __init__(self, file_obj):
        self.file_obj = file_obj
        self.block = None
        self.block_idx = 0
        self.block_offset = 0

    def read(self, size):
        remain = size
        blocks = self.file_obj.blocks
        ret = ""

        while True:
            if not self.block or self.block_offset == len(self.block):
                if self.block_idx == len(blocks):
                    break
                self.block = SeafBlock(self.file_obj.store_id,
                                       self.file_obj.version,
                                       blocks[self.block_idx]).read()
                self.block_idx += 1
                self.block_offset = 0

            if self.block_offset + remain >= len(self.block)-1:
                ret += self.block[self.block_offset:]
                self.block_offset = len(self.block)
                remain -= (len(self.block) - self.block_offset)
            else:
                ret += self.block[self.block_offset:self.block_offset+remain]
                self.block_offset += remain
                remain = 0

            if remain == 0:
                break

        return ret

    def close(self):
        pass

#===============================================================================
# SeafileResource
#===============================================================================
class SeafileResource(DAVNonCollection):
    def __init__(self, path, repo, rel_path, obj, environ):
        super(SeafileResource, self).__init__(path, environ)
        self.repo = repo
        self.rel_path = rel_path
        self.obj = obj
        self.username = environ.get("http_authenticator.username", "")

    # Getter methods for standard live properties
    def getContentLength(self):
        return self.obj.filesize
    def getContentType(self):
#        (mimetype, _mimeencoding) = mimetypes.guess_type(self.path)
#        print "mimetype(%s): %r, %r" % (self.path, mimetype, _mimeencoding)
#        if not mimetype:
#            mimetype = "application/octet-stream"
#        print "mimetype(%s): return %r" % (self.path, mimetype)
#        return mimetype
        return util.guessMimeType(self.path)
    def getCreationDate(self):
#        return int(time.time())
        return None
    def getDisplayName(self):
        return self.name
    def getEtag(self):
        return self.obj.obj_id

    def getLastModified(self):
        cached_mtime = getattr(self.obj, 'last_modified', None)
        if cached_mtime:
            return cached_mtime

        parent, filename = os.path.split(self.rel_path)
        mtimes = seafile_api.get_files_last_modified(self.repo.id, parent, -1)
        for mtime in mtimes:
            if (mtime.file_name.encode('utf-8') == filename):
                return mtime.last_modified

        return None

    def supportEtag(self):
        return True
    def supportRanges(self):
        return False

    def getContent(self):
        """Open content as a stream for reading.

        See DAVResource.getContent()
        """
        assert not self.isCollection
        return SeafileStream(self.obj)


    def beginWrite(self, contentType=None):
        """Open content as a stream for writing.

        See DAVResource.beginWrite()
        """
        assert not self.isCollection
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission(self.repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        fd, path = tempfile.mkstemp(dir=self.provider.tmpdir)
        self.tmpfile_path = path
        return os.fdopen(fd, "wb")

    def endWrite(self, withErrors):
        if not withErrors:
            parent, filename = os.path.split(self.rel_path)
            seafile_api.put_file(self.repo.id, self.tmpfile_path, parent, filename,
                                 self.username, None)
        os.unlink(self.tmpfile_path)

    def handleDelete(self):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission(self.repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        parent, filename = os.path.split(self.rel_path)
        seafile_api.del_file(self.repo.id, parent, filename, self.username)

        return True

    def handleMove(self, destPath):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        parts = destPath.strip("/").split("/", 1)
        if len(parts) <= 1:
            raise DAVError(HTTP_BAD_REQUEST)
        repo_name = parts[0]
        rel_path = parts[1]

        dest_dir, dest_file = os.path.split(rel_path)
        dest_repo = getRepoByName(repo_name, self.username)

        if seafile_api.check_permission(dest_repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        src_dir, src_file = os.path.split(self.rel_path)
        if not src_file:
            raise DAVError(HTTP_BAD_REQUEST)

        if not seafile_api.is_valid_filename(dest_repo.id, dest_file):
            raise DAVError(HTTP_BAD_REQUEST)

        # some clients such as GoodReader requires "overwrite" semantics
        file_id_dest = seafile_api.get_file_id_by_path(dest_repo.id, rel_path)
        if file_id_dest != None:
            seafile_api.del_file(dest_repo.id, dest_dir, dest_file, self.username)

        copy_result = seafile_api.move_file(self.repo.id, src_dir, src_file,
                              dest_repo.id, dest_dir, dest_file, self.username, NEED_PROGRESS)

        copy_background_hack(copy_result)

        return True

    def handleCopy(self, destPath, depthInfinity):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        parts = destPath.strip("/").split("/", 1)
        if len(parts) <= 1:
            raise DAVError(HTTP_BAD_REQUEST)
        repo_name = parts[0]
        rel_path = parts[1]

        dest_dir, dest_file = os.path.split(rel_path)
        dest_repo = getRepoByName(repo_name, self.username)

        if seafile_api.check_permission(dest_repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        src_dir, src_file = os.path.split(self.rel_path)
        if not src_file:
            raise DAVError(HTTP_BAD_REQUEST)

        if not seafile_api.is_valid_filename(dest_repo.id, dest_file):
            raise DAVError(HTTP_BAD_REQUEST)

        copy_result = seafile_api.copy_file(self.repo.id, src_dir, src_file,
                              dest_repo.id, dest_dir, dest_file, self.username, NEED_PROGRESS)

        copy_background_hack(copy_result)

        return True

#===============================================================================
# SeafDirResource
#===============================================================================
class SeafDirResource(DAVCollection):
    def __init__(self, path, repo, rel_path, obj, environ):
        super(SeafDirResource, self).__init__(path, environ)
        self.repo = repo
        self.rel_path = rel_path
        self.obj = obj
        self.username = environ.get("http_authenticator.username", "")

    # Getter methods for standard live properties
    def getCreationDate(self):
#        return int(time.time())
        return None
    def getDisplayName(self):
        return self.name
    def getDirectoryInfo(self):
        return None
    def getEtag(self):
        return self.obj.obj_id
    def getLastModified(self):
#        return int(time.time())
        return None

    def getMemberNames(self):
        namelist = []
        for e in self.obj.dirs:
            namelist.append(e[0])
        for e in self.obj.files:
            namelist.append(e[0])
        return namelist

    def getMember(self, name):
        member_rel_path = "/".join([self.rel_path, name])
        member_path = "/".join([self.path, name])
        member = self.obj.lookup(name)

        if not member:
            raise DAVError(HTTP_NOT_FOUND)

        if isinstance(member, SeafFile):
            return SeafileResource(member_path, self.repo, member_rel_path, member, self.environ)
        else:
            return SeafDirResource(member_path, self.repo, member_rel_path, member, self.environ)

    def getMemberList(self):
        member_list = []
        d = self.obj

        if d.version == 0:
            file_mtimes = []
            try:
                file_mtimes = seafile_api.get_files_last_modified(self.repo.id, self.rel_path, -1)
            except:
                raise DAVError(HTTP_INTERNAL_ERROR)

            mtimes = UTF8Dict()
            for entry in file_mtimes:
                mtimes[entry.file_name] = entry.last_modified
        for name, dent in d.dirents.iteritems():
            member_path = utf8_path_join(self.path, name)
            member_rel_path = utf8_path_join(self.rel_path, name)

            if dent.is_dir():
                obj = SeafDir(d.store_id, d.version, dent.id)
                obj.load()
                res = SeafDirResource(member_path, self.repo, member_rel_path, obj, self.environ)
            elif dent.is_file():
                obj = SeafFile(d.store_id, d.version, dent.id)
                obj.load()
                res = SeafileResource(member_path, self.repo, member_rel_path, obj, self.environ)
            else:
                continue

            if d.version == 1:
                obj.last_modified = dent.mtime
            else:
                obj.last_modified = mtimes[name]

            member_list.append(res)

        return member_list

    # --- Read / write ---------------------------------------------------------

    def createEmptyResource(self, name):
        """Create an empty (length-0) resource.

        See DAVResource.createEmptyResource()
        """
        assert not "/" in name
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission(self.repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        try:
            seafile_api.post_empty_file(self.repo.id, self.rel_path, name, self.username)
        except SearpcError, e:
            if e.msg == 'Invalid file name':
                raise DAVError(HTTP_BAD_REQUEST)
            raise

        # Repo was updated, can't use self.repo
        repo = seafile_api.get_repo(self.repo.id)
        if not repo:
            raise DAVError(HTTP_INTERNAL_ERROR)

        member_rel_path = "/".join([self.rel_path, name])
        member_path = "/".join([self.path, name])
        obj = resolveRepoPath(repo, member_rel_path)
        if not obj or not isinstance(obj, SeafFile):
            raise DAVError(HTTP_INTERNAL_ERROR)

        return SeafileResource(member_path, repo, member_rel_path, obj, self.environ)

    def createCollection(self, name):
        """Create a new collection as member of self.

        See DAVResource.createCollection()
        """
        assert not "/" in name
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission(self.repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        if not seafile_api.is_valid_filename(self.repo.id, name):
            raise DAVError(HTTP_BAD_REQUEST)

        seafile_api.post_dir(self.repo.id, self.rel_path, name, self.username)

    def handleDelete(self):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission(self.repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        parent, filename = os.path.split(self.rel_path)
        # Can't delete repo root
        if not filename:
            raise DAVError(HTTP_BAD_REQUEST)

        seafile_api.del_file(self.repo.id, parent, filename, self.username)

        return True

    def handleMove(self, destPath):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        parts = destPath.strip("/").split("/", 1)
        if len(parts) <= 1:
            raise DAVError(HTTP_BAD_REQUEST)
        repo_name = parts[0]
        rel_path = parts[1]

        dest_dir, dest_file = os.path.split(rel_path)
        dest_repo = getRepoByName(repo_name, self.username)

        if seafile_api.check_permission(dest_repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        src_dir, src_file = os.path.split(self.rel_path)
        if not src_file:
            raise DAVError(HTTP_BAD_REQUEST)

        if not seafile_api.is_valid_filename(dest_repo.id, dest_file):
            raise DAVError(HTTP_BAD_REQUEST)

        copy_result = seafile_api.move_file(self.repo.id, src_dir, src_file,
                              dest_repo.id, dest_dir, dest_file, self.username, NEED_PROGRESS)

        copy_background_hack(copy_result)

        return True

    def handleCopy(self, destPath, depthInfinity):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        parts = destPath.strip("/").split("/", 1)
        if len(parts) <= 1:
            raise DAVError(HTTP_BAD_REQUEST)
        repo_name = parts[0]
        rel_path = parts[1]

        dest_dir, dest_file = os.path.split(rel_path)
        dest_repo = getRepoByName(repo_name, self.username)

        if seafile_api.check_permission(dest_repo.id, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        src_dir, src_file = os.path.split(self.rel_path)
        if not src_file:
            raise DAVError(HTTP_BAD_REQUEST)

        if not seafile_api.is_valid_filename(dest_repo.id, dest_file):
            raise DAVError(HTTP_BAD_REQUEST)

        copy_result = seafile_api.copy_file(self.repo.id, src_dir, src_file,
                              dest_repo.id, dest_dir, dest_file, self.username, NEED_PROGRESS)

        copy_background_hack(copy_result)

        return True

class RootResource(DAVCollection):
    def __init__(self, username, environ):
        super(RootResource, self).__init__("/", environ)
        self.username = username

    # Getter methods for standard live properties
    def getCreationDate(self):
#        return int(time.time())
        return None
    def getDisplayName(self):
        return ""
    def getDirectoryInfo(self):
        return None
    def getEtag(self):
        return None
    def getLastModified(self):
#        return int(time.time())
        return None

    def getMemberNames(self):
        all_repos = getAccessibleRepos(self.username)

        name_hash = {}
        for r in all_repos:
            r_list = name_hash[r.name]
            if not r_list:
                name_hash[r.name] = [r]
            else:
                r_list.append(r)

        namelist = []
        for r_list in name_hash.values():
            if len(r_list) == 1:
                repo = r_list[0]
                namelist.append(repo.name)
            else:
                for repo in r_list:
                    unique_name = repo.name + "-" + repo.id
                    namelist.append(unique_name)

        return namelist

    def getMember(self, name):
        repo = getRepoByName(name, self.username)
        return self._createRootRes(repo, name)

    def getMemberList(self):
        """
        Overwrite this method for better performance.
        The default implementation call getMemberNames() then call getMember()
        for each name. This calls getAccessibleRepos() for too many times.
        """
        all_repos = getAccessibleRepos(self.username)

        name_hash = {}
        for r in all_repos:
            r_list = name_hash.get(r.name, [])
            if not r_list:
                name_hash[r.name] = [r]
            else:
                r_list.append(r)

        member_list = []
        for r_list in name_hash.values():
            if len(r_list) == 1:
                repo = r_list[0]
                res = self._createRootRes(repo, repo.name)
                member_list.append(res)
            else:
                for repo in r_list:
                    unique_name = repo.name + "-" + repo.id
                    res = self._createRootRes(repo, unique_name)
                    member_list.append(res)

        return member_list

    def _createRootRes(self, repo, name):
        obj = get_repo_root_seafdir(repo)
        return SeafDirResource("/"+name, repo, "", obj, self.environ)

    # --- Read / write ---------------------------------------------------------

    def createEmptyResource(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def createCollection(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def handleDelete(self):
        raise DAVError(HTTP_FORBIDDEN)

    def handleMove(self, destPath):
        raise DAVError(HTTP_FORBIDDEN)

    def handleCopy(self, destPath, depthInfinity):
        raise DAVError(HTTP_FORBIDDEN)


#===============================================================================
# SeafileProvider
#===============================================================================
class SeafileProvider(DAVProvider):

    def __init__(self, readonly=False):
        super(SeafileProvider, self).__init__()
        self.readonly = readonly
        self.tmpdir = os.path.join(SEAFILE_CONF_DIR, "webdavtmp")
        if not os.access(self.tmpdir, os.F_OK):
            os.mkdir(self.tmpdir)

    def __repr__(self):
        rw = "Read-Write"
        if self.readonly:
            rw = "Read-Only"
        return "%s for Seafile (%s)" % (self.__class__.__name__, rw)


    def getResourceInst(self, path, environ):
        """Return info dictionary for path.

        See DAVProvider.getResourceInst()
        """
        self._count_getResourceInst += 1

        username = environ.get("http_authenticator.username", "")

        if path == "/" or path == "":
            return RootResource(username, environ)

        path = path.rstrip("/")
        try:
            repo, rel_path, obj = resolvePath(path, username)
        except DAVError, e:
            if e.value == HTTP_NOT_FOUND:
                return None
            raise

        if isinstance(obj, SeafDir):
            return SeafDirResource(path, repo, rel_path, obj, environ)
        return SeafileResource(path, repo, rel_path, obj, environ)

def resolvePath(path, username):
    segments = path.strip("/").split("/")
    if len(segments) == 0:
        raise DAVError(HTTP_BAD_REQUEST)
    repo_name = segments.pop(0)

    repo = getRepoByName(repo_name, username)

    rel_path = ""
    obj = get_repo_root_seafdir(repo)

    n_segs = len(segments)
    i = 0
    for segment in segments:
        obj = obj.lookup(segment)

        if not obj or (isinstance(obj, SeafFile) and i != n_segs-1):
            raise DAVError(HTTP_NOT_FOUND)

        rel_path += "/" + segment
        i += 1

    return (repo, rel_path, obj)

def resolveRepoPath(repo, path):
    segments = path.strip("/").split("/")

    obj = get_repo_root_seafdir(repo)

    n_segs = len(segments)
    i = 0
    for segment in segments:
        obj = obj.lookup(segment)

        if not obj or (isinstance(obj, SeafFile) and i != n_segs-1):
            return None

        i += 1

    return obj

def get_repo_root_seafdir(repo):
    root_id = seafObj.get_commit_root_id(repo.id, repo.version, repo.head_cmmt_id)
    obj = SeafDir(repo.store_id, repo.version, root_id)
    obj.load()
    return obj

def getRepoByName(repo_name, username):
    repos = getAccessibleRepos(username)

    ret_repo = None
    for repo in repos:
        if repo.name == repo_name:
            ret_repo = repo
            break

    if not ret_repo:
        for repo in repos:
            if repo.name + "-" + repo.id == repo_name:
                ret_repo = repo
                break
        if not ret_repo:
            raise DAVError(HTTP_NOT_FOUND)

    return ret_repo

def getAccessibleRepos(username):
    all_repos = {}

    def addRepo(repo_id):
        try:
            if all_repos.has_key(repo_id):
                return
            repo = seafile_api.get_repo(repo_id)
            if repo:
                all_repos[repo_id] = repo
        except SearpcError, e:
            util.warn("Failed to get repo %.8s: %s" % (repo_id, e.msg))

    try:
        owned_repos = seafile_api.get_owned_repo_list(username)
    except SearpcError, e:
        util.warn("Failed to list owned repos: %s" % e.msg)

    for orepo in owned_repos:
        addRepo(orepo.id)

    try:
        shared_repos = seafile_api.get_share_in_repo_list(username, -1, -1)
    except SearpcError, e:
        util.warn("Failed to list shared repos: %s" % e.msg)

    for srepo in shared_repos:
        addRepo(srepo.repo_id)

    try:
        joined_groups = seaserv.get_personal_groups_by_user(username)
    except SearpcError, e:
        util.warn("Failed to get groups for %s" % username)
    for g in joined_groups:
        try:
            group_repos = seafile_api.get_group_repo_list(g.id)
            for repo in group_repos:
                if all_repos.has_key(repo.id):
                    continue
                all_repos[repo.id] = repo
        except SearpcError, e:
            util.warn("Failed to list repos in group %d" % g.id)

    # Don't include encrypted repos
    ret = []
    for repo in all_repos.values():
        if not repo.encrypted:
            repo.name = repo.name.encode('utf-8')
            ret.append(repo)

    return ret

def copy_background_hack(copy_result):
    '''If the copy/move operation is a backgroud task, sleep 1 second'''
    if getattr(copy_result, 'background', False):
        time.sleep(1)