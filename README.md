# Seafile WebDAV Server [![Build Status](https://secure.travis-ci.org/haiwen/seafdav.svg?branch=master)](http://travis-ci.org/haiwen/seafdav)

This is the WebDAV server for seafile.

See [Seafile Server Manual](http://manual.seafile.com/extension/webdav.html) for details.

# Running
There are several steps to configuring your environment:
- Edit `run.sh.template` and  modify `CCNET_CONF_DIR` and `SEAFILE_CONF_DIR` to your Seafile server's settings.
- Add the path of `seafobj` to your PYTHONPATH env.

There are one template for running seafdav:
- `run.sh.template`: This is for running seafdav on the default 8080 port with a gunicorn server.

To run on 8080 port:
```
cp run.sh.template run.sh
./run.sh
```

# Testing

- start local seafile server
- start local seahub server (While seafdav itself doesn't require seahub, we use seahub webapi as a driver for testing)
- start seafdav server
- create a test user `test@seafiltest.com` with password `test`
- Run the tests
```
export CCNET_CONF_DIR=/path/to/ccnet
export SEAFILE_CONF_DIR=/path/to/seafile-data
./functest.sh test
```
