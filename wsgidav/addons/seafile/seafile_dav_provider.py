from wsgidav.dav_error import DAVError, HTTP_BAD_REQUEST, HTTP_FORBIDDEN, \
    HTTP_NOT_FOUND, HTTP_INTERNAL_ERROR
from wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection

import wsgidav.util as util
import os
#import mimetypes
import tempfile

import seaserv
from seaserv import seafile_api, CALC_SHARE_USAGE
from seaserv import check_quota as check_repo_quota
from pysearpc import SearpcError
from seafobj import commit_mgr, fs_mgr
from seafobj.fs import SeafFile, SeafDir
from wsgidav.addons.seafile.seaf_utils import SEAFILE_CONF_DIR, UTF8Dict, utf8_path_join, utf8_wrap

__docformat__ = "reStructuredText"

_logger = util.getModuleLogger(__name__)

NEED_PROGRESS = 0
SYNCHRONOUS = 1

INFINITE_QUOTA = -2

def sort_repo_list(repos):
    return sorted(repos, lambda r1, r2: cmp(r1.id, r2.id))

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
        self.org_id = environ.get("seafile.org_id", "")
        self.is_guest = environ.get("seafile.is_guest", False)
        self.tmpfile_path = None
        self.owner = None

    # Getter methods for standard live properties
    def getContentLength(self):
        return self.obj.size
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
        return utf8_wrap(self.obj.obj_id)

    def getLastModified(self):
        cached_mtime = getattr(self.obj, 'last_modified', None)
        if cached_mtime:
            return cached_mtime

        if self.obj.mtime > 0:
            return self.obj.mtime

        # XXX: What about not return last modified for files in v0 repos,
        # since they can be too expensive sometimes?
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
        return self.obj.get_stream()

    def check_repo_owner_quota(self, isnewfile=True, contentlength=-1):
        """Check if the upload would cause the user quota be exceeded

        `contentlength` is only positive when the client does not use "transfer-encode: chunking"

        Return True if the quota would not be exceeded, otherwise return False.
        """
        if contentlength <= 0:
            # When client use "transfer-encode: chunking", the content length
            # is not included in the request headers
            if isnewfile:
                return check_repo_quota(self.repo.id) >= 0
            else:
                return True
        else:
            delta = contentlength - self.obj.size
            return check_repo_quota(self.repo.id, delta) >= 0

    def beginWrite(self, contentType=None, isnewfile=True, contentlength=-1):
        """Open content as a stream for writing.

        See DAVResource.beginWrite()
        """
        assert not self.isCollection
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission_by_path(self.repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        if not self.check_repo_owner_quota(isnewfile, contentlength):
            raise DAVError(HTTP_FORBIDDEN, "The quota of the repo owner is exceeded")

        fd, path = tempfile.mkstemp(dir=self.provider.tmpdir)
        self.tmpfile_path = path
        return os.fdopen(fd, "wb")

    def endWrite(self, withErrors, isnewfile=True):
        if not withErrors:
            parent, filename = os.path.split(self.rel_path)
            contentlength = os.stat(self.tmpfile_path).st_size
            if not self.check_repo_owner_quota(isnewfile=isnewfile, contentlength=contentlength):
                raise DAVError(HTTP_FORBIDDEN, "The quota of the repo owner is exceeded")
            seafile_api.put_file(self.repo.id, self.tmpfile_path, parent, filename,
                                 self.username, None)
        if self.tmpfile_path:
            try:
                os.unlink(self.tmpfile_path)
            finally:
                self.tmpfile_path = None

    def handleDelete(self):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission_by_path(self.repo.id, self.rel_path, self.username) != "rw":
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
        dest_repo = getRepoByName(repo_name, self.username, self.org_id, self.is_guest)

        if seafile_api.check_permission_by_path(dest_repo.id, self.rel_path, self.username) != "rw":
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

        seafile_api.move_file(self.repo.id, src_dir, src_file,
                              dest_repo.id, dest_dir, dest_file, 1, self.username, NEED_PROGRESS, SYNCHRONOUS)

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
        dest_repo = getRepoByName(repo_name, self.username, self.org_id, self.is_guest)

        if seafile_api.check_permission_by_path(dest_repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        src_dir, src_file = os.path.split(self.rel_path)
        if not src_file:
            raise DAVError(HTTP_BAD_REQUEST)

        if not seafile_api.is_valid_filename(dest_repo.id, dest_file):
            raise DAVError(HTTP_BAD_REQUEST)

        seafile_api.copy_file(self.repo.id, src_dir, src_file,
                              dest_repo.id, dest_dir, dest_file, self.username, NEED_PROGRESS, SYNCHRONOUS)

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
        self.org_id = environ.get("seafile.org_id", "")
        self.is_guest = environ.get("seafile.is_guest", False)

    # Getter methods for standard live properties
    def getCreationDate(self):
#        return int(time.time())
        return None
    def getDisplayName(self):
        return self.name
    def getDirectoryInfo(self):
        return None
    def getEtag(self):
        return utf8_wrap(self.obj.obj_id)
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
                obj = fs_mgr.load_seafdir(d.store_id, d.version, dent.id)
                res = SeafDirResource(member_path, self.repo, member_rel_path, obj, self.environ)
            elif dent.is_file():
                obj = fs_mgr.load_seafile(d.store_id, d.version, dent.id)
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

        if seafile_api.check_permission_by_path(self.repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        if check_repo_quota(self.repo.id) < 0:
            raise DAVError(HTTP_FORBIDDEN, "The quota of the repo owner is exceeded")

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

        if seafile_api.check_permission_by_path(self.repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        if not seafile_api.is_valid_filename(self.repo.id, name):
            raise DAVError(HTTP_BAD_REQUEST)

        seafile_api.post_dir(self.repo.id, self.rel_path, name, self.username)

    def handleDelete(self):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission_by_path(self.repo.id, self.rel_path, self.username) != "rw":
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
        dest_repo = getRepoByName(repo_name, self.username, self.org_id, self.is_guest)

        if seafile_api.check_permission_by_path(dest_repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        src_dir, src_file = os.path.split(self.rel_path)
        if not src_file:
            raise DAVError(HTTP_BAD_REQUEST)

        if not seafile_api.is_valid_filename(dest_repo.id, dest_file):
            raise DAVError(HTTP_BAD_REQUEST)

        seafile_api.move_file(self.repo.id, src_dir, src_file,
                              dest_repo.id, dest_dir, dest_file, 0, self.username, NEED_PROGRESS, SYNCHRONOUS)

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
        dest_repo = getRepoByName(repo_name, self.username, self.org_id, self.is_guest)

        if seafile_api.check_permission_by_path(dest_repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        src_dir, src_file = os.path.split(self.rel_path)
        if not src_file:
            raise DAVError(HTTP_BAD_REQUEST)

        if not seafile_api.is_valid_filename(dest_repo.id, dest_file):
            raise DAVError(HTTP_BAD_REQUEST)

        seafile_api.copy_file(self.repo.id, src_dir, src_file,
                              dest_repo.id, dest_dir, dest_file, self.username, NEED_PROGRESS, SYNCHRONOUS)

        return True

class RootResource(DAVCollection):
    def __init__(self, username, environ):
        super(RootResource, self).__init__("/", environ)
        self.username = username
        self.org_id = environ.get('seafile.org_id', '')
        self.is_guest = environ.get('seafile.is_guest', False)

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
        all_repos = getAccessibleRepos(self.username, self.org_id, self.is_guest)

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
                for repo in sort_repo_list(r_list):
                    unique_name = repo.name + "-" + repo.id[:6].encode('utf-8')
                    namelist.append(unique_name)

        return namelist

    def getMember(self, name):
        repo = getRepoByName(name, self.username, self.org_id, self.is_guest)
        return self._createRootRes(repo, name)

    def getMemberList(self):
        """
        Overwrite this method for better performance.
        The default implementation call getMemberNames() then call getMember()
        for each name. This calls getAccessibleRepos() for too many times.
        """
        all_repos = getAccessibleRepos(self.username, self.org_id, self.is_guest)

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
                for repo in sort_repo_list(r_list):
                    unique_name = repo.name + "-" + repo.id[:6].encode('utf-8')
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
        org_id = environ.get("seafile.org_id", "")
        is_guest = environ.get("seafile.is_guest", False)

        if path == "/" or path == "":
            return RootResource(username, environ)

        path = path.rstrip("/")
        try:
            repo, rel_path, obj = resolvePath(path, username, org_id, is_guest)
        except DAVError, e:
            if e.value == HTTP_NOT_FOUND:
                return None
            raise

        if isinstance(obj, SeafDir):
            return SeafDirResource(path, repo, rel_path, obj, environ)
        return SeafileResource(path, repo, rel_path, obj, environ)

def resolvePath(path, username, org_id, is_guest):
    segments = path.strip("/").split("/")
    if len(segments) == 0:
        raise DAVError(HTTP_BAD_REQUEST)
    repo_name = segments.pop(0)

    repo = getRepoByName(repo_name, username, org_id, is_guest)

    rel_path = ""
    obj = get_repo_root_seafdir(repo)

    n_segs = len(segments)
    i = 0
    parent = None
    for segment in segments:
        parent = obj
        obj = parent.lookup(segment)

        if not obj or (isinstance(obj, SeafFile) and i != n_segs-1):
            raise DAVError(HTTP_NOT_FOUND)

        rel_path += "/" + segment
        i += 1

    if parent:
        obj.mtime = parent.lookup_dent(segment).mtime

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
    root_id = commit_mgr.get_commit_root_id(repo.id, repo.version, repo.head_cmmt_id)
    return fs_mgr.load_seafdir(repo.store_id, repo.version, root_id)

def getRepoByName(repo_name, username, org_id, is_guest):
    repos = getAccessibleRepos(username, org_id, is_guest)

    ret_repo = None
    for repo in repos:
        if repo.name == repo_name:
            ret_repo = repo
            break

    if not ret_repo:
        for repo in repos:
            if repo.name + "-" + repo.id[:6].encode('utf-8') == repo_name:
                ret_repo = repo
                break
        if not ret_repo:
            raise DAVError(HTTP_NOT_FOUND)

    return ret_repo

def getAccessibleRepos(username, org_id, is_guest):
    all_repos = {}

    def addRepo(repo_id):
        try:
            if all_repos.has_key(repo_id):
                return
            repo = seafile_api.get_repo(repo_id)
            if repo and not repo.encrypted:
                repo.name = repo.name.encode('utf-8')
                all_repos[repo_id] = repo
        except SearpcError, e:
            util.warn("Failed to get repo %.8s: %s" % (repo_id, e.msg))

    try:
        owned_repos = get_owned_repos(username, org_id)
    except SearpcError, e:
        util.warn("Failed to list owned repos: %s" % e.msg)

    for orepo in owned_repos:
        if not orepo.is_virtual:
            addRepo(orepo.id)

    try:
        shared_repos = get_share_in_repo_list(username, org_id)
    except SearpcError, e:
        util.warn("Failed to list shared repos: %s" % e.msg)

    for srepo in shared_repos:
        addRepo(srepo.repo_id)

    try:
        groups = get_groups_by_user(username, org_id)
        repo_ids = get_group_repos(username, org_id, groups)
    except SearpcError, e:
        util.warn("Failed to get groups for %s" % username)
    for repo_id in repo_ids:
        addRepo(repo_id)

    for repo in list_inner_pub_repos(username, org_id, is_guest):
        addRepo(repo.repo_id)

    return all_repos.values()

def get_owned_repos(username, org_id):
    if org_id:
        return seafile_api.get_org_owned_repo_list(org_id, username)
    else:
        return seafile_api.get_owned_repo_list(username)

def get_share_in_repo_list(username, org_id):
    """List share in repos.
    """
    if org_id:
        repo_list = seafile_api.get_org_share_in_repo_list(org_id, username,
                                                           -1, -1)
    else:
        repo_list = seafile_api.get_share_in_repo_list(username, -1, -1)

    # for repo in repo_list:
    #     repo.user_perm = seafile_api.check_repo_access_permission(repo.repo_id,
    #                                                               username)
    return repo_list

def get_groups_by_user(username, org_id):
    """List user groups.
    """
    if org_id:
        return seaserv.get_org_groups_by_user(org_id, username)
    else:
        return seaserv.get_personal_groups_by_user(username)

def get_group_repos(username, org_id, groups):
    """Get repos shared to groups.
    """
    group_repos = []
    if org_id:
        # For each group I joined...
        for grp in groups:
            # Get group repos, and for each group repos...
            for r_id in seafile_api.get_org_group_repoids(org_id, grp.id):
                # No need to list my own repo
                repo_owner = seafile_api.get_org_repo_owner(r_id)
                if repo_owner == username:
                    continue
                group_repos.append(r_id)
    else:
        # For each group I joined...
        for grp in groups:
            # Get group repos, and for each group repos...
            for r_id in seafile_api.get_group_repoids(grp.id):
                # No need to list my own repo
                repo_owner = seafile_api.get_repo_owner(r_id)
                if repo_owner == username:
                    continue
                group_repos.append(r_id)
    return group_repos

def get_repo_last_modify(repo):
    """ Get last modification time for a repo.

    If head commit id of a repo is provided, we use that commit as last commit,
    otherwise falls back to getting last commit of a repo which is time
    consuming.
    """
    last_cmmt = None
    if repo.head_cmmt_id is not None:
        last_cmmt = seaserv.get_commit(repo.id, repo.version, repo.head_cmmt_id)
    return last_cmmt.ctime if last_cmmt else 0


def list_inner_pub_repos(username, org_id, is_guest):
    if is_guest:
        return []

    if org_id:
        return seaserv.list_org_inner_pub_repos(org_id, username)

    return seaserv.list_inner_pub_repos(username)
