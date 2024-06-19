#!/bin/bash

export SEAFDAV_CONF=/data/conf/seafdav.conf

# Your ccnet conf dir
export CCNET_CONF_DIR=/data/conf/
# Your seafile conf dir
export SEAFILE_CONF_DIR=/data/conf/seafile-data

export SEAFILE_CENTRAL_CONF_DIR=/data/conf/

export SEAHUB_DIR=/data/dev/seahub/
# export DJANGO_SETTINGS_MODULE=seahub.settings


# Your extra python path.
export PYTHONPATH=/usr/lib/python3.8/dist-packages:/usr/lib/python3.8/site-packages:/usr/local/lib/python3.8/dist-packages:/usr/local/lib/python3.8/site-packages:/data/dev/seahub/:/data/dev/seafdav:/data/conf/:$PYTHONPATH

pkill -f "wsgidav"

python3 -m wsgidav.server.server_cli --verbose --server gunicorn --root / --log-file /data/logs/seafdav.log --pid /data/pids/seafdav.pid --port 8080 --host 0.0.0.0
