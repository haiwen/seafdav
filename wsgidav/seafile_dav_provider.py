from wsgidav.dav_error import DAVError, HTTP_BAD_REQUEST, HTTP_FORBIDDEN, \
    HTTP_NOT_FOUND, HTTP_INTERNAL_ERROR
from wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection

import wsgidav.util as util
import os
import posixpath

import tempfile

from seaserv import seafile_api, CALC_SHARE_USAGE
from pysearpc import SearpcError
from seafobj import commit_mgr, fs_mgr
from seafobj.fs import SeafFile, SeafDir
from wsgidav.dc.seaf_utils import SEAFILE_CONF_DIR

__docformat__ = "reStructuredText"

_logger = util.get_module_logger(__name__)

NEED_PROGRESS = 0
SYNCHRONOUS = 1

INFINITE_QUOTA = -2

def sort_repo_list(repos):
    return sorted(repos, key = lambda r: r.id)

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
    def get_content_length(self):
        return self.obj.size
    def get_content_type(self):
#        (mimetype, _mimeencoding) = mimetypes.guess_type(self.path)
#        print "mimetype(%s): %r, %r" % (self.path, mimetype, _mimeencoding)
#        if not mimetype:
#            mimetype = "application/octet-stream"
#        print "mimetype(%s): return %r" % (self.path, mimetype)
#        return mimetype
        return util.guess_mime_type(self.path)
    def get_creation_date(self):
#        return int(time.time())
        return None
    def get_display_name(self):
        return self.name
    def get_etag(self):
        return self.obj.obj_id

    def get_last_modified(self):
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
            if (mtime.file_name == filename):
                return mtime.last_modified

        return None

    def support_etag(self):
        return True
    def support_ranges(self):
        return False

    def get_content(self):
        """Open content as a stream for reading.

        See DAVResource.getContent()
        """
        assert not self.is_collection
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
                return seafile_api.check_quota(self.repo.id) >= 0
            else:
                return True
        else:
            delta = contentlength - self.obj.size
            return seafile_api.check_quota(self.repo.id, delta) >= 0

    def begin_write(self, content_type=None, isnewfile=True, contentlength=-1):
        """Open content as a stream for writing.

        See DAVResource.beginWrite()
        """
        assert not self.is_collection
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission_by_path(self.repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        if not self.check_repo_owner_quota(isnewfile, contentlength):
            raise DAVError(HTTP_FORBIDDEN, "The quota of the repo owner is exceeded")

        fd, path = tempfile.mkstemp(dir=self.provider.tmpdir)
        self.tmpfile_path = path
        return os.fdopen(fd, "wb")

    def end_write(self, with_errors, isnewfile=True):
        if not with_errors:
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

    def handle_delete(self):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission_by_path(self.repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        parent, filename = os.path.split(self.rel_path)
        seafile_api.del_file(self.repo.id, parent, filename, self.username)

        return True

    def handle_move(self, dest_path):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        parts = dest_path.strip("/").split("/", 1)
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

    def handle_copy(self, dest_path, depth_infinity):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        parts = dest_path.strip("/").split("/", 1)
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
    def get_creation_date(self):
#        return int(time.time())
        return None
    def get_display_name(self):
        return self.name
    def get_directory_info(self):
        return None
    def get_etag(self):
        return self.obj.obj_id
    def get_last_modified(self):
#        return int(time.time())
        return None

    def get_member_names(self):
        namelist = []
        for e in self.obj.dirs:
            namelist.append(e[0])
        for e in self.obj.files:
            namelist.append(e[0])
        return namelist

    def get_member(self, name):
        member_rel_path = "/".join([self.rel_path, name])
        member_path = "/".join([self.path, name])
        member = self.obj.lookup(name)

        if not member:
            raise DAVError(HTTP_NOT_FOUND)

        if isinstance(member, SeafFile):
            return SeafileResource(member_path, self.repo, member_rel_path, member, self.environ)
        else:
            return SeafDirResource(member_path, self.repo, member_rel_path, member, self.environ)

    def get_member_list(self):
        member_list = []
        d = self.obj

        if d.version == 0:
            file_mtimes = []
            try:
                file_mtimes = seafile_api.get_files_last_modified(self.repo.id, self.rel_path, -1)
            except:
                raise DAVError(HTTP_INTERNAL_ERROR)

            mtimes = {}
            for entry in file_mtimes:
                mtimes[entry.file_name] = entry.last_modified
        for name, dent in d.dirents.items():
            member_path = posixpath.join(self.path, name)
            member_rel_path = posixpath.join(self.rel_path, name)

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
    def create_empty_resource(self, name):
        """Create an empty (length-0) resource.

        See DAVResource.createEmptyResource()
        """
        assert not "/" in name
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_permission_by_path(self.repo.id, self.rel_path, self.username) != "rw":
            raise DAVError(HTTP_FORBIDDEN)

        if seafile_api.check_quota(self.repo.id) < 0:
            raise DAVError(HTTP_FORBIDDEN, "The quota of the repo owner is exceeded")

        try:
            seafile_api.post_empty_file(self.repo.id, self.rel_path, name, self.username)
        except SearpcError as e:
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

    def create_collection(self, name):
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

    def handle_delete(self):
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

    def handle_move(self, dest_path):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        parts = dest_path.strip("/").split("/", 1)
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

    def handle_copy(self, dest_path, depth_infinity):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        parts = dest_path.strip("/").split("/", 1)
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
    def __init__(self, username, environ, show_repo_id):
        super(RootResource, self).__init__("/", environ)
        self.username = username
        self.show_repo_id = show_repo_id
        self.org_id = environ.get('seafile.org_id', '')
        self.is_guest = environ.get('seafile.is_guest', False)

    # Getter methods for standard live properties
    def get_creation_date(self):
#        return int(time.time())
        return None
    def get_display_name(self):
        return ""
    def get_directory_info(self):
        return None
    def get_etag(self):
        return None
    def getLastModified(self):
#        return int(time.time())
        return None

    def get_member_names(self):
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
                    unique_name = repo.name + "-" + repo.id[:6]
                    namelist.append(unique_name)

        return namelist

    def get_member(self, name):
        repo = getRepoByName(name, self.username, self.org_id, self.is_guest)
        return self._createRootRes(repo, name)

    def get_member_list(self):
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
                unique_name = repo.name
                if self.show_repo_id:
                    unique_name = repo.name + "-" + repo.id[:6]
                res = self._createRootRes(repo, unique_name)
                member_list.append(res)
            else:
                for repo in sort_repo_list(r_list):
                    unique_name = repo.name + "-" + repo.id[:6]
                    res = self._createRootRes(repo, unique_name)
                    member_list.append(res)

        return member_list

    def _createRootRes(self, repo, name):
        obj = get_repo_root_seafdir(repo)
        return SeafDirResource("/"+name, repo, "", obj, self.environ)

    # --- Read / write ---------------------------------------------------------

    def create_empty_resource(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def create_collection(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def handle_delete(self):
        raise DAVError(HTTP_FORBIDDEN)

    def handle_move(self, dest_path):
        raise DAVError(HTTP_FORBIDDEN)

    def handle_copy(self, dest_path, depth_infinity):
        raise DAVError(HTTP_FORBIDDEN)


#===============================================================================
# SeafileProvider
#===============================================================================
class SeafileProvider(DAVProvider):

    def __init__(self, show_repo_id, readonly=False):
        super(SeafileProvider, self).__init__()
        self.readonly = readonly
        self.show_repo_id = show_repo_id
        self.tmpdir = os.path.join(SEAFILE_CONF_DIR, "webdavtmp")
        if not os.access(self.tmpdir, os.F_OK):
            os.mkdir(self.tmpdir)

    def __repr__(self):
        rw = "Read-Write"
        if self.readonly:
            rw = "Read-Only"
        return "%s for Seafile (%s)" % (self.__class__.__name__, rw)


    def get_resource_inst(self, path, environ):
        """Return info dictionary for path.

        See DAVProvider.getResourceInst()
        """
        self._count_get_resource_inst += 1

        username = environ.get("http_authenticator.username", "")
        org_id = environ.get("seafile.org_id", "")
        is_guest = environ.get("seafile.is_guest", False)

        if path == "/" or path == "":
            return RootResource(username, environ, self.show_repo_id)

        path = path.rstrip("/")
        try:
            repo, rel_path, obj = resolvePath(path, username, org_id, is_guest)
        except DAVError as e:
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
            if repo.name + "-" + repo.id[:6] == repo_name:
                ret_repo = repo
                break
        if not ret_repo:
            raise DAVError(HTTP_NOT_FOUND)

    return ret_repo

def getAccessibleRepos(username, org_id, is_guest):
    all_repos = {}

    def addRepo(repo):
        if all_repos.get(repo.repo_id):
            return
        if not repo.encrypted:
            all_repos[repo.repo_id] = repo

    try:
        owned_repos = get_owned_repos(username, org_id)
    except SearpcError as e:
        util.warn("Failed to list owned repos: %s" % e.msg)

    for orepo in owned_repos:
        if orepo:
            # store_id is used by seafobj to access fs object.
            # repo's store_id is equal to repo_id except virtual_repo.
            orepo.store_id = orepo.repo_id
            addRepo(orepo)

    try:
        shared_repos = get_share_in_repo_list(username, org_id)
    except SearpcError as e:
        util.warn("Failed to list shared repos: %s" % e.msg)

    for srepo in shared_repos:
        if srepo:
            addRepo(srepo)
            pass

    try:
        repos = get_group_repos(username, org_id)
    except SearpcError as e:
        util.warn("Failed to get groups for %s" % username)
    for grepo in repos:
        if grepo: 
            addRepo(grepo)

    for prepo in list_inner_pub_repos(username, org_id, is_guest):
        if prepo:
            addRepo(prepo)

    return all_repos.values()

def get_group_repos(username, org_id):
    if org_id:
        return seafile_api.get_org_group_repos_by_user(username, org_id)
    else:
        return seafile_api.get_group_repos_by_user(username)

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

    return repo_list

def list_inner_pub_repos(username, org_id, is_guest):
    if is_guest:
        return []

    if org_id:
        return seafile_api.list_org_inner_pub_repos(org_id)

    return seafile_api.get_inner_pub_repo_list()
