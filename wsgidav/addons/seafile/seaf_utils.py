#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import posixpath
import ConfigParser
import wsgidav.util as util

_logger = util.getModuleLogger(__name__)


def _load_path_from_env(key, check=True):
    v = os.environ.get(key, '')
    if not v:
        if check:
            raise ImportError(
                "seaf_util cannot be imported, because environment variable %s is undefined." % key)
        else:
            return None
    return os.path.normpath(os.path.expanduser(v))

CCNET_CONF_DIR = _load_path_from_env('CCNET_CONF_DIR')
SEAFILE_CONF_DIR = _load_path_from_env('SEAFILE_CONF_DIR')
SEAFILE_CENTRAL_CONF_DIR = _load_path_from_env(
    'SEAFILE_CENTRAL_CONF_DIR', check=False)


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
    args = [utf8_wrap(arg) for arg in args]
    return posixpath.join(*args)

_multi_tenancy_enabled = None


def multi_tenancy_enabled():
    global _multi_tenancy_enabled
    if _multi_tenancy_enabled is None:
        _multi_tenancy_enabled = False
        try:
            cp = ConfigParser.ConfigParser()
            cp.read(
                os.path.join(SEAFILE_CENTRAL_CONF_DIR if SEAFILE_CENTRAL_CONF_DIR else SEAFILE_CONF_DIR, 'seafile.conf'))
            if cp.has_option('general', 'multi_tenancy'):
                _multi_tenancy_enabled = cp.getboolean(
                    'general', 'multi_tenancy')
        except:
            _logger.exception('failed to read multi_tenancy')
    return _multi_tenancy_enabled
