#coding: UTF-8

import os
import ConfigParser

class InvalidConfigError(Exception):
    '''This type of Exception is rasied when error happens during parsing
    seafile.conf

    '''
    def __init__(self, msg):
        Exception.__init__(self)
        self.msg = msg

    def __str__(self):
        return self.msg

class SeafS3Client(object):
    '''Wraps a s3 connection and a bucket'''
    def __init__(self, key_id, key, bucket_name):
        import boto
        from boto.s3.key import Key

        globals()['boto'] = boto
        globals()['Key'] = Key

        self.key_id = key_id
        self.key = key
        self.bucket_name = bucket_name

        self.conn = None
        self.bucket = None

    def do_connect(self):
        self.conn = boto.connect_s3(self.key_id, self.key)
        self.bucket = self.conn.get_bucket(self.bucket_name)

    def read_object_content(self, obj_id):
        if not self.conn:
            self.do_connect()

        k = Key(bucket=self.bucket, name=obj_id)

        return k.get_contents_as_string()

def id_to_path(dirname, obj_id):
    '''Utility method to format a fs/commits/blocks object path'''
    return os.path.join(dirname, obj_id[:2], obj_id[2:])

class SeafObjBackend(object):
    '''Base class of seafile object backend'''
    def __init__(self, obj_type):
        self.obj_type = obj_type

    def read_obj(self, obj_id):
        raise NotImplementedError

class SeafObjBackendFS(SeafObjBackend):
    def __init__(self, obj_type, obj_dir):
        SeafObjBackend.__init__(self, obj_type)
        self.obj_dir = obj_dir

    def read_obj(self, obj_id):
        path = id_to_path(self.obj_dir, obj_id)
        with open(path, 'rb') as fp:
            d = fp.read()

        return d

    def __str__(self):
        return 'FS Object Backend(obj_type = %s, obj_dir = %s)' % (self.obj_type, self.obj_dir)

class SeafObjBackendS3(SeafObjBackend):
    def __init__(self, obj_type, key_id, key, bucket_name):
        SeafObjBackend.__init__(self, obj_type)
        self.client = SeafS3Client(key_id, key, bucket_name)

    def read_obj(self, obj_id):
        return self.client.read_object_content(obj_id)

    def __str__(self):
        return 'S3 Object Backend(obj_type = %s)' % self.obj_type


class SeafBlockBackend(object):
    '''Base class of seafile block backend'''
    def __init__(self):
        pass

    def read_block(self, block_id):
        raise NotImplementedError

class SeafBlockBackendFS(SeafBlockBackend):
    def __init__(self, block_dir):
        SeafBlockBackend.__init__(self)
        self.block_dir = block_dir

    def read_block(self, block_id):
        path = id_to_path(self.block_dir, block_id)
        with open(path, 'rb') as fp:
            d = fp.read()

        return d

    def __str__(self):
        return 'FS Block Backend(block_dir = %s)' % self.block_dir


class SeafBlockBackendS3(SeafBlockBackend):
    def __init__(self, key_id, key, bucket_name):
        SeafBlockBackend.__init__(self)
        self.client = SeafS3Client(key_id, key, bucket_name)

    def read_block(self, block_id):
        return self.client.read_object_content(block_id)

    def __str__(self):
        return 'S3 Block Backend'


def load_s3_config_common(section, config):
    key_id = config.get(section, 'key_id')
    key = config.get(section, 'key')
    bucket = config.get(section, 'bucket')

    return key_id, key, bucket


def load_obj_backend_fs(obj_type, section, config):
    obj_dir = config.get(section, 'object_dir')

    backend = SeafObjBackendFS(obj_type, obj_dir)
    return backend

def load_obj_backend_s3(obj_type, section, config):
    key_id, key, bucket = load_s3_config_common(section, config)

    backend = SeafObjBackendS3(obj_type, key_id, key, bucket)
    return backend

def get_obj_backend(obj_type, config, seafile_conf_dir):
    '''Load object backend from conf'''
    if obj_type == 'commits':
        section = 'commit_object_backend'
    elif obj_type == 'fs':
        section = 'fs_object_backend'
    else:
        raise InvalidConfigError('invalid obj type %s' % obj_type)

    if config.has_option(section, 'name'):
        name = config.get(section, 'name')
        if name == 'filesystem':
            obj_backend = load_obj_backend_fs(obj_type, section, config)
        elif name == 's3':
            obj_backend = load_obj_backend_s3(obj_type, section, config)
        else:
            raise InvalidConfigError('Unknown commit object backend %s' % name)
    else:
        # Defaults to fs backend, obj_dir = <seafdir>/<obj_type>/
        obj_backend = SeafObjBackendFS(obj_type, os.path.join(seafile_conf_dir, obj_type))

    return obj_backend

def load_block_backend_fs(config):
    block_dir = config.get('block_backend', 'block_dir')

    backend = SeafBlockBackendFS(block_dir)
    return backend

def load_block_backend_s3(config):
    key_id, key, bucket = load_s3_config_common('block_backend', config)

    backend = SeafBlockBackendS3(key_id, key, bucket)
    return backend

def get_block_backend(config, seafile_conf_dir):
    section = 'block_backend'
    if config.has_option(section, 'name'):
        name = config.get(section, 'name')
        if name == 'filesystem':
            obj_backend = load_block_backend_fs(config)
        elif name == 's3':
            obj_backend = load_block_backend_s3(config)
        else:
            raise InvalidConfigError('Unknown block backend %s' % name)
    else:
        # Defaults to fs backend
        obj_backend = SeafBlockBackendFS((os.path.join(seafile_conf_dir, 'blocks')))

    return obj_backend

def _load_backends(seafile_conf_dir):
    seafile_conf = os.path.join(seafile_conf_dir, 'seafile.conf')
    config = ConfigParser.ConfigParser()
    config.read(seafile_conf)

    commit_backend = get_obj_backend('commits', config, seafile_conf_dir)
    fs_backend = get_obj_backend('fs', config, seafile_conf_dir)
    block_backend = get_block_backend(config, seafile_conf_dir)

    return (commit_backend, fs_backend, block_backend)

def load_backends(seafile_conf_dir):
    try:
        return _load_backends(seafile_conf_dir)
    except (ConfigParser.NoSectionError, ConfigParser.NoOptionError, InvalidConfigError) as e:
        raise Exception('invalid conf in seafile.conf: %s' % e)
