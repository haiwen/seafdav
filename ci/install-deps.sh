#!/bin/bash

set -e -x

git clone --depth=1 --branch=master git://github.com/haiwen/libevhtp /tmp/libevhtp
cd /tmp/libevhtp
cmake -DEVHTP_DISABLE_SSL=ON -DEVHTP_BUILD_SHARED=OFF .
make -j2
sudo make install
cd -

git clone --depth=1 --branch=master git://github.com/haiwen/libsearpc /tmp/libsearpc
cd /tmp/libsearpc
./autogen.sh
./configure
make -j2
sudo make install
cd -

git clone --depth=1 --branch=master git://github.com/haiwen/seafile-server /tmp/seafile-server
cd /tmp/seafile-server
./autogen.sh
./configure
make -j2
sudo make install
cd -

sudo ldconfig

git clone --depth=1 --branch=master git://github.com/haiwen/seafobj /tmp/seafobj
