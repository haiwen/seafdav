#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

def get_seafile_conf_dir():
    try:
        SEAFILE_CONF_DIR = os.environ['SEAFILE_CONF_DIR']
    except KeyError:
        raise RuntimeError('SEAFILE_CONF_DIR is not set')

    return SEAFILE_CONF_DIR

SEAFILE_CONF_DIR = get_seafile_conf_dir()

def get_ccnet_conf_dir():
    try:
        CCNET_CONF_DIR = os.environ['CCNET_CONF_DIR']
    except KeyError:
        raise RuntimeError('CCNET_CONF_DIR is not set')

    return CCNET_CONF_DIR

CCNET_CONF_DIR = get_ccnet_conf_dir()

def utf8_wrap(s):
    if isinstance(s, unicode):
        s = s.encode('utf-8')

    return s

class UTF8Dict(dict):
    '''A dict whose keys are always converted to utf8, so we don't need to
    care whether the param for the key is in utf-8 or unicode when set/get

    '''
    def __init__(self):
        dict.__init__(self)

    def __setitem__(self, k, v):
        dict.__setitem__(self, utf8_wrap(k), v)

    def __getitem__(self, k):
        return dict.__getitem__(self, utf8_wrap(k))


def utf8_path_join(*args):
    args = [ utf8_wrap(arg) for arg in args ]
    return os.path.join(*args)
