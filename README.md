# Seafile WebDAV Server [![Build Status](https://secure.travis-ci.org/haiwen/seafdav.svg?branch=master)](http://travis-ci.org/haiwen/seafdav)

This is the WebDAV server for seafile.

See [Seafile Server Manual](http://manual.seafile.com/extension/webdav.html) for details.

# Running

There are a template for running seafdav:
- run.sh.template: This is for running seafdav on the default 8080 port with a built-in CherryPy server.

To run on 8080 port:

```
cp run.sh.template run.sh
```

  - The [python-pam](https://github.com/FirefighterBlu3/python-pam) library is 
    needed as extra requirement if pam-login authentication is used on Linux 
    or OSX:
    ```
    $ pip install wsgidav[pam]
    $ wsgidav --host=0.0.0.0 --port=8080 --root=/tmp --auth=pam-login
    ```
Then change CCNET_CONF_DIR and SEAFILE_CONF_DIR to your Seafile server's settings.

# Testing

- start local seafile server
- start local seahub server (While seafdav itself doesn't require seahub, we use seahub webapi as a driver for testing)
- start seafdav server
- create a test user `test@seafiletest.com` with password `test`
- Run the tests
```
export CCNET_CONF_DIR=/path/to/ccnet
export SEAFILE_CONF_DIR=/path/to/seafile-data
./ci/functest.sh test
```
