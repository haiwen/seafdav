#coding: UTF-8

from tests.davclient import SeafDavClient
from nose.tools import assert_equal

def test_list_top_level():
    dav = SeafDavClient()
    dirents = dav.ls('/')
    assert_equal(len(dirents), 1)


