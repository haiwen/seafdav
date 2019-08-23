#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import configparser
import wsgidav.util as util

_logger = util.get_module_logger(__name__)


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

_multi_tenancy_enabled = None


def multi_tenancy_enabled():
    global _multi_tenancy_enabled
    if _multi_tenancy_enabled is None:
        _multi_tenancy_enabled = False
        try:
            cp = configparser.ConfigParser()
            cp.read(
                os.path.join(SEAFILE_CENTRAL_CONF_DIR if SEAFILE_CENTRAL_CONF_DIR else SEAFILE_CONF_DIR, 'seafile.conf'))
            if cp.has_option('general', 'multi_tenancy'):
                _multi_tenancy_enabled = cp.getboolean(
                    'general', 'multi_tenancy')
        except:
            _logger.exception('failed to read multi_tenancy')
    return _multi_tenancy_enabled
