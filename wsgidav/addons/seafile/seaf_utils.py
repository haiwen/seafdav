#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2013 Seafile, Inc
# Licensed under the terms of seafile-pro-license.txt.
# You are not allowed to modify or redistribute this file.
#

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
