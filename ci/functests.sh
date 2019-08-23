set -e
if [ $# -lt "1" ]; then
    echo
    echo "Usage: ./functests.sh {init|runserver|test}"
    echo
    exit 1
fi
if [ ${TRAVIS} ] ;then
    set -x
    CCNET_CONF_DIR="/tmp/seafile-server/tests/conf"
    SEAFILE_CONF_DIR="/tmp/seafile-server/tests/conf/seafile-data"
    PYTHONPATH="/usr/local/lib/python3.6/site-packages:/tmp/seafobj:${PYTHONPATH}"
    export PYTHONPATH
    export CCNET_CONF_DIR
    export SEAFILE_CONF_DIR

fi

function start_server() {
    ccnet-server -c /tmp/seafile-server/tests/conf -f - &
    seaf-server -c /tmp/seafile-server/tests/conf -d /tmp/seafile-server/tests/conf/seafile-data -f -l - &
    sleep 2
}

function init() {
    mkdir /tmp/seafile-server/tests/conf/seafile-data
    touch /tmp/seafile-server/tests/conf/seafile-data/seafile.conf
    cat > /tmp/seafile-server/tests/conf/seafile-data/seafile.conf << EOF
[database]							   
create_tables = true
EOF
    touch ${CCNET_CONF_DIR}/seafile.ini
    cat > ${CCNET_CONF_DIR}/seafile.ini << EOF
/tmp/seafile-server/tests/conf/seafile-data
EOF
    start_server
    python -c "from seaserv import ccnet_api as api;api.add_emailuser('test@seafiletest.com','test',0,1)"    
}

function start_seafdav() {
    if [ ${TRAVIS} ]; then
	cd ${TRAVIS_BUILD_DIR}
	python -m wsgidav.server.server_cli --host=127.0.0.1 --port=8080 --root=/ --server=gunicorn &
	sleep 5
    fi    
}

function run_tests() {
    cd seafdav_tests
    py.test
}

case $1 in
    "init")
        init
        ;;
    "runserver")
        start_seafdav
        ;;
    "test")
        run_tests
        ;;
    *)
        echo "unknow command \"$1\""
        ;;
esac

