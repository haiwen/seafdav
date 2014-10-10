# Seafile WebDAV Server [![Build Status](https://secure.travis-ci.org/haiwen/seafdav.svg?branch=lins)](http://travis-ci.org/haiwen/seafdav)

This is the WebDAV server for seafile.

See [Seafile Server Manual](http://manual.seafile.com/extension/webdav.html) for details.


# Testing

- start local seafile server
- start local seahub server (While seafdav itself doesn't require seahub, we use seahub webapi as a driver for testing)
- start seafdav server
- create a test user `test@seafiltest.com` with password `testtest`
- Run the tests
```
export CCNET_CONF_DIR=/path/to/ccnet
export SEAFILE_CONF_DIR=/path/to/seafile-data
./functest.sh test
```
