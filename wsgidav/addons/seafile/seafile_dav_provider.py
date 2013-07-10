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

import seaserv
from seaserv import seafile_api
from pysearpc import SearpcError
from seafObj import *

__docformat__ = "reStructuredText"

_logger = util.getModuleLogger(__name__)


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
                self.block = SeafBlock(blocks[self.block_idx]).read()
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
        return int(time.time())
    def getDisplayName(self):
        return self.name
    def getEtag(self):
        return self.obj.obj_id
    def getLastModified(self):
        return int(time.time())
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
        raise DAVError(HTTP_FORBIDDEN)

    
    def delete(self):
        """Remove this resource or collection (recursive).
        
        See DAVResource.delete()
        """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)               
        raise DAVError(HTTP_FORBIDDEN)
            

    def copyMoveSingle(self, destPath, isMove):
        """See DAVResource.copyMoveSingle() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)               
        raise DAVError(HTTP_FORBIDDEN)
               

    def supportRecursiveMove(self, destPath):
        """Return True, if moveRecursive() is available (see comments there)."""
        return True

    
    def moveRecursive(self, destPath):
        """See DAVResource.moveRecursive() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)               
        raise DAVError(HTTP_FORBIDDEN)
               


    
#===============================================================================
# SeafDirResource
#===============================================================================
class SeafDirResource(DAVCollection):
    def __init__(self, path, repo, rel_path, obj, environ):
        super(SeafDirResource, self).__init__(path, environ)
        self.repo = repo
        self.rel_path = rel_path
        self.obj = obj

    # Getter methods for standard live properties     
    def getCreationDate(self):
        return int(time.time())
    def getDisplayName(self):
        return self.name
    def getDirectoryInfo(self):
        return None
    def getEtag(self):
        return self.obj.obj_id
    def getLastModified(self):
        return int(time.time())

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
        for e in self.obj.dirs:
            member = SeafDir(e[1])
            member.load()
            member_path = "/".join([self.path, e[0]])
            member_rel_path = "/".join([self.rel_path, e[0]])
            res = SeafDirResource(member_path, self.repo, member_rel_path, member, self.environ)
            member_list.append(res)
        for e in self.obj.files:
            member = SeafFile(e[1])
            member.load()
            member_path = "/".join([self.path, e[0]])
            member_rel_path = "/".join([self.rel_path, e[0]])
            res = SeafileResource(member_path, self.repo, member_rel_path, member, self.environ)
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
        raise DAVError(HTTP_FORBIDDEN)
    

    def createCollection(self, name):
        """Create a new collection as member of self.
        
        See DAVResource.createCollection()
        """
        assert not "/" in name
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)               
        raise DAVError(HTTP_FORBIDDEN)

    def delete(self):
        """Remove this resource or collection (recursive).
        
        See DAVResource.delete()
        """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)               
        raise DAVError(HTTP_FORBIDDEN)
            

    def copyMoveSingle(self, destPath, isMove):
        """See DAVResource.copyMoveSingle() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)               
        raise DAVError(HTTP_FORBIDDEN)
               

    def supportRecursiveMove(self, destPath):
        """Return True, if moveRecursive() is available (see comments there)."""
        return True

    
    def moveRecursive(self, destPath):
        """See DAVResource.moveRecursive() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)               
        raise DAVError(HTTP_FORBIDDEN)
               

class RootResource(DAVCollection):
    def __init__(self, username, environ):
        super(RootResource, self).__init__("/", environ)
        self.username = username

    # Getter methods for standard live properties     
    def getCreationDate(self):
        return int(time.time())
    def getDisplayName(self):
        return ""
    def getDirectoryInfo(self):
        return None
    def getEtag(self):
        return None
    def getLastModified(self):
        return int(time.time())

    def getMemberNames(self):
        all_repos = self.provider.getAccessibleRepos(self.username)

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
        repo = self.provider.getRepoByName(name, self.username)
        return self._createRootRes(repo, name)

    def getMemberList(self):
        """
        Overwrite this method for better performance.
        The default implementation call getMemberNames() then call getMember()
        for each name. This calls getAccessibleRepos() for too many times.
        """
        all_repos = self.provider.getAccessibleRepos(self.username)

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
        root_id = get_commit_root_id(repo.head_cmmt_id)
        obj = SeafDir(root_id)
        obj.load()
        return SeafDirResource("/"+name, repo, "/", obj, self.environ)

    # --- Read / write ---------------------------------------------------------
    
    def createEmptyResource(self, name):
        raise DAVError(HTTP_FORBIDDEN)
    

    def createCollection(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def delete(self):
        raise DAVError(HTTP_FORBIDDEN)
            

    def copyMoveSingle(self, destPath, isMove):
        raise DAVError(HTTP_FORBIDDEN)
               

    def supportRecursiveMove(self, destPath):
        return True

    
    def moveRecursive(self, destPath):
        raise DAVError(HTTP_FORBIDDEN)
    
#===============================================================================
# SeafileProvider
#===============================================================================
class SeafileProvider(DAVProvider):

    def __init__(self, readonly=False):
        super(SeafileProvider, self).__init__()
        self.readonly = readonly
        
    def __repr__(self):
        rw = "Read-Write"
        if self.readonly:
            rw = "Read-Only"
        return "%s for Seafile (%s)" % (self.__class__.__name__, rw)

    def resolvePath(self, path, username):
        segments = path.strip("/").split("/")
        if len(segments) == 0:
            raise DAVError(HTTP_BAD_REQUEST)
        repo_name = segments.pop(0)

        repo = self.getRepoByName(repo_name, username)

        rel_path = ""
        root_id = get_commit_root_id(repo.head_cmmt_id)
        obj = SeafDir(root_id)
        obj.load()

        n_segs = len(segments)
        i = 0
        for segment in segments:
            obj = obj.lookup(segment)

            if not obj or (isinstance(obj, SeafFile) and i != n_segs-1):
                raise DAVError(HTTP_NOT_FOUND)

            rel_path += "/" + segment
            i += 1

        return (repo, rel_path, obj)

    def getRepoByName(self, repo_name, username):
        repos = self.getAccessibleRepos(username)

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

    def getAccessibleRepos(self, username):
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

        return all_repos.values()

    def getResourceInst(self, path, environ):
        """Return info dictionary for path.

        See DAVProvider.getResourceInst()
        """
        self._count_getResourceInst += 1

        username = environ.get("http_authenticator.username", "")

        if path == "/" or path == "":
            return RootResource(username, environ)

        repo, rel_path, obj = self.resolvePath(path, username)

        if isinstance(obj, SeafDir):
            return SeafDirResource(path, repo, rel_path, obj, environ)
        return SeafileResource(path, repo, rel_path, obj, environ)
