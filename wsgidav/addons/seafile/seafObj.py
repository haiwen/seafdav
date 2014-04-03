#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2013 Seafile, Inc
# Licensed under the terms of seafile-pro-license.txt.
# You are not allowed to modify or redistribute this file.
#

import wsgidav.util as util
import stat
import struct
import json
import binascii
import os
import zlib

from seaf_utils import SEAFILE_CONF_DIR, UTF8Dict
import backends

ZERO_OBJ_ID = '0000000000000000000000000000000000000000'

SEAF_METADATA_TYPE_FILE = 1
SEAF_METADATA_TYPE_LINK = 2
SEAF_METADATA_TYPE_DIR = 3

commit_backend, fs_backend, block_backend = backends.load_backends(SEAFILE_CONF_DIR)

class SeafMetaExecption(Exception):
    def __init__(self, obj_type, obj_id):
        Exception.__init__(self)
        self.msg = '%s object %s format error' % (obj_type, obj_id)

        def __str__(self):
            return self.msg

class SeafObj(object):
    backend = None
    def __init__(self, store_id, version, obj_id):
        self.version = version
        self.store_id = store_id
        self.obj_id = obj_id
        self.buf = ''

    def load_data(self):
        if self.obj_id == ZERO_OBJ_ID:
            self.buf = ''
        else:
            self.buf = self.backend.read_obj(self.store_id, self.version, self.obj_id)

class SeafDirent(object):
    DIR = 0
    FILE = 1
    def __init__(self, name, type, id, mtime, size):
        self.name = name
        self.type = type
        self.id = id
        self.mtime = mtime
        self.size = size

    def is_file(self):
        return self.type == SeafDirent.FILE

    def is_dir(self):
        return self.type == SeafDirent.DIR

    @staticmethod
    def fromV0(name, type, id):
        return SeafDirent(name, type, id, -1, -1)

    @staticmethod
    def fromV1(name, type, id, mtime, size):
        return SeafDirent(name, type, id, mtime, size)


class SeafDir(SeafObj):
    backend = fs_backend

    def __init__(self, store_id, version, dir_id):
        SeafObj.__init__(self, store_id, version, dir_id)
        self.dirents = UTF8Dict()
        # self.files = []
        # self.dirs = []

    def load(self):
        if self.obj_id == ZERO_OBJ_ID:
            # an empty dir
            return
        self.load_data()

        if self.version == 0:
            self.parse_dirents_v0()
        elif self.version == 1:
            self.parse_dirents_v1()

    def parse_dirents_v0(self):
        '''uncompressed, binary format'''
        mode, = struct.unpack_from("!i", self.buf, offset = 0)
        if mode != SEAF_METADATA_TYPE_DIR:
            raise SeafMetaExecption('dir', self.obj_id)

        off = 4
        while True:
            fmt = "!i40si"
            mode, eid, name_len = struct.unpack_from(fmt, self.buf, offset = off)
            off += struct.calcsize(fmt)

            fmt = "!%ds" % name_len
            name, = struct.unpack_from(fmt, self.buf, offset = off)
            off += struct.calcsize(fmt)

            if stat.S_ISREG(mode):
                self.dirents[name] = SeafDirent.fromV0(name, SeafDirent.FILE, eid)
                # self.files.append((name, eid))
            elif stat.S_ISDIR(mode):
                self.dirents[name] = SeafDirent.fromV0(name, SeafDirent.DIR, eid)
                # self.dirs.append((name, eid))
            else:
                util.warn('Error: unknown object mode %s', mode)
            if off > len(self.buf) - 48:
                break

    def parse_dirents_v1(self):
        '''compressed, json format'''
        content = zlib.decompress(self.buf)
        d = json.loads(content)

        for entry in d['dirents']:
            name = entry['name']
            id = entry['id']
            mtime = entry['mtime']
            mode = entry['mode']
            if stat.S_ISREG(mode):
                type = SeafDirent.FILE
                size = entry['size']
            elif stat.S_ISDIR(mode):
                type = SeafDirent.DIR
                size = 0
            else:
                continue

            self.dirents[name] = SeafDirent.fromV1(name, type, id, mtime, size)

    def lookup(self, name):
        if name not in self.dirents:
            return None

        dent = self.dirents[name]
        if dent.is_dir():
            obj = SeafDir(self.store_id, self.version, dent.id)
        else:
            obj = SeafFile(self.store_id, self.version, dent.id)

        obj.load()

        return obj

class SeafFile(SeafObj):
    backend = fs_backend
    def __init__(self, store_id, version, file_id):
        SeafObj.__init__(self, store_id, version, file_id)
        self.blocks = []
        self.filesize = 0

    def load(self):
        if self.obj_id == ZERO_OBJ_ID:
            return
        self.load_data()
        if self.version == 0:
            self.parse_blocks_v0()
        else:
            self.parse_blocks_v1()

    def parse_blocks_v0(self):
        '''uncompressed, binray format'''
        fmt = '!iq'
        mode, self.filesize = struct.unpack_from(fmt, self.buf, offset = 0)
        if mode != SEAF_METADATA_TYPE_FILE:
            raise SeafMetaExecption('file', self.obj_id)

        off = struct.calcsize(fmt)
        while True:
            fmt = "!20s"
            bid, = struct.unpack_from(fmt, self.buf, offset = off)
            hexs = []
            for d in bid:
                x = binascii.b2a_hex(d)
                hexs.append(x)

            blk_id = ''.join(hexs)
            self.blocks.append(blk_id)

            off += struct.calcsize(fmt)
            if off > len(self.buf) - 20:
                break

    def parse_blocks_v1(self):
        ''''compressed, json format'''
        content = zlib.decompress(self.buf)
        d = json.loads(content)

        self.blocks = d['block_ids']
        self.filesize = d['size']

class SeafBlock(object):
    backend = block_backend
    def __init__(self, store_id, version, block_id):
        self.store_id = store_id
        self.version = version
        self.block_id = block_id

    def read(self):
        return self.backend.read_block(self.store_id, self.version, self.block_id)

class SeafCommit(object):
    backend = commit_backend
    def __init__(self, repo_id, version, commit_id):
        self.repo_id = repo_id
        self.version = version
        self.commit_id = commit_id
        self.content = None
        self.buf = ''

    def load_data(self):
        if self.commit_id == ZERO_OBJ_ID:
            self.buf = ''
        else:
            self.buf = self.backend.read_obj(self.repo_id, self.version, self.commit_id)

    def load(self):
        if self.content:
            return self.content

        self.load_data()
        self.content = json.loads(self.buf)

    def get(self, *args):
        self.load()
        return self.content.get(*args)

def get_commit_root_id(repo_id, version, commit_id):
    commit = SeafCommit(repo_id, version, commit_id)
    commit.load()
    return commit.get('root_id')

def load_commit(repo_id, version, commit_id):
    commit = SeafCommit(repo_id, version, commit_id)
    commit.load()
    return commit
