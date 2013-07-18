#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2013 Seafile, Inc
# Licensed under the terms of seafile-pro-license.txt.
# You are not allowed to modify or redistribute this file.
#

import wsgidav.util
import stat
import struct
import json
import binascii
import os

from seaf_utils import SEAFILE_CONF_DIR
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
    def __init__(self, obj_id):
        self.obj_id = obj_id
        self.buf = None

    def load_data(self):
        if self.obj_id == ZERO_OBJ_ID:
            self.buf = ''
        else:
            self.buf = self.backend.read_obj(self.obj_id)

class SeafDir(SeafObj):
    backend = fs_backend
    load_count = 0

    def __init__(self, dir_id):
        SeafObj.__init__(self, dir_id)
        self.files = []
        self.dirs = []

    def load(self):
        if self.obj_id == ZERO_OBJ_ID:
            return
        SeafDir.load_count += 1
        self.load_data()
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
                self.files.append((name, eid))
            elif stat.S_ISDIR(mode):
                self.dirs.append((name, eid))
            else:
                util.warn('Error: unknown object mode %s', mode)
            if off > len(self.buf) - 48:
                break

    def lookup(self, name):
        obj_id = ""
        for entry in self.files:
            if entry[0] == name:
                obj_id = entry[1]
                mode = SEAF_METADATA_TYPE_FILE
                break
        if not obj_id:
            for entry in self.dirs:
                if entry[0] == name:
                    obj_id = entry[1]
                    mode = SEAF_METADATA_TYPE_DIR
                    break
        if not obj_id:
            return None

        obj = None
        if mode == SEAF_METADATA_TYPE_FILE:
            obj = SeafFile(obj_id)
            obj.load()
        else:
            obj = SeafDir(obj_id)
            obj.load()

        return obj

class SeafCommit(SeafObj):
    backend = commit_backend
    load_count = 0
    def __init__(self, commit_id):
        SeafObj.__init__(self, commit_id)
        self.content = None

    def load(self):
        if self.content:
            return self.content

        SeafCommit.load_count += 1
        self.load_data()
        self.content = json.loads(self.buf)

    def get(self, *args):
        self.load()
        return self.content.get(*args)

class SeafFile(SeafObj):
    backend = fs_backend
    load_count = 0
    def __init__(self, file_id):
        SeafObj.__init__(self, file_id)
        self.blocks = []
        self.filesize = 0

    def load(self):
        if self.obj_id == ZERO_OBJ_ID:
            return
        SeafFile.load_count += 1
        self.load_data()
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

class SeafBlock(object):
    backend = block_backend
    load_count = 0
    def __init__(self, block_id):
        self.block_id = block_id

    def read(self):
        SeafBlock.load_count += 1
        return self.backend.read_block(self.block_id)

def get_commit_root_id(commit_id):
    commit = SeafCommit(commit_id)
    commit.load()
    return commit.get('root_id')

def load_commit(commit_id):
    commit = SeafCommit(commit_id)
    commit.load()
    return commit
