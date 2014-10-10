#!/bin/bash

[ -r /etc/default/seafile-server ] && . /etc/default/seafile-server

: ${PYTHON=python}

: ${SEAFILE_TEST_USERNAME="test@seafiletest.com"}
: ${SEAFILE_TEST_PASSWORD="testtest"}
: ${SEAFILE_TEST_ADMIN_USERNAME="admin@seafiletest.com"}
: ${SEAFILE_TEST_ADMIN_PASSWORD="adminadmin"}

: ${SEAFDAV_MOUNT_POINT="/tmp/seafile-webdav"}


export SEAFILE_TEST_USERNAME
export SEAFILE_TEST_PASSWORD
export SEAFILE_TEST_ADMIN_USERNAME
export SEAFILE_TEST_ADMIN_PASSWORD

# If you run this script on your local machine, you must set CCNET_CONF_DIR
# and SEAFILE_CONF_DIR like this:
#
#       export CCNET_CONF_DIR=/your/path/to/ccnet
#       export SEAFILE_CONF_DIR=/your/path/to/seafile-data
#

set -e
if [[ ${TRAVIS} != "" ]]; then
    set -x
fi

SCRIPT=$(readlink -f "$0")
SEAFDAV_SRCDIR=$(dirname "${SCRIPT}")

export PYTHONPATH="/usr/local/lib/python2.7/site-packages:/usr/lib/python2.7/site-packages:${SEAHUB_SRCDIR}/thirdpart:${PYTHONPATH}"
export SEAFDAV_CONF=${SEAFDAV_SRCDIR}/seafdav.conf.sample
cd "$SEAFDAV_SRCDIR"

function init() {
    ###############################
    # create database and two new users: an admin, and a normal user
    ###############################
    # create normal user
    $PYTHON -c "import ccnet; pool = ccnet.ClientPool('${CCNET_CONF_DIR}'); ccnet_threaded_rpc = ccnet.CcnetThreadedRpcClient(pool, req_pool=True); ccnet_threaded_rpc.add_emailuser('${SEAFILE_TEST_USERNAME}', '${SEAFILE_TEST_PASSWORD}', 0, 1);"
    # create admin
    $PYTHON -c "import ccnet; pool = ccnet.ClientPool('${CCNET_CONF_DIR}'); ccnet_threaded_rpc = ccnet.CcnetThreadedRpcClient(pool, req_pool=True); ccnet_threaded_rpc.add_emailuser('${SEAFILE_TEST_ADMIN_USERNAME}', '${SEAFILE_TEST_ADMIN_PASSWORD}', 1, 1);"
}

function start_seafdav() {
    python -m wsgidav.server.run_server --log-file /tmp/seafdav.log --port 8080 --host 127.0.0.1 &
    sleep 5
}

function run_tests() {
    set +e
    nosetests $nose_opts
    rvalue=$?
    cd -
    if [[ ${TRAVIS} != "" ]]; then
        # On travis-ci, dump seahub logs when test finished
        for logfile in /tmp/seafdav*.log; do
            echo -e "\nLog file $logfile:\n"
            cat "${logfile}"
            echo
        done
    fi
    exit $rvalue
}

if [[ $# < 1 ]]; then
    echo
    echo "Usage: ./functests.sh {init|runserver|test}"
    echo
    exit 1
fi

case $1 in
    "init")
        init
        ;;
    "runserver")
        start_seafdav
        ;;
    "test")
        shift
        nose_opts=$*
        run_tests
        ;;
    *)
        echo "unknow command \"$1\""
        ;;
esac
