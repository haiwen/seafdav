#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import configparser
import wsgidav.util as util

import ldap
from ldap import sasl
from ldap import filter

import seahub_settings

ENABLE_LDAP = getattr(seahub_settings, 'ENABLE_LDAP', False)
LDAP_SERVER_URL = getattr(seahub_settings, 'LDAP_SERVER_URL', '')
LDAP_BASE_DN = getattr(seahub_settings, 'LDAP_BASE_DN', '')
LDAP_ADMIN_DN = getattr(seahub_settings, 'LDAP_ADMIN_DN', '')
LDAP_ADMIN_PASSWORD = getattr(seahub_settings, 'LDAP_ADMIN_PASSWORD', '')
LDAP_LOGIN_ATTR = getattr(seahub_settings, 'LDAP_LOGIN_ATTR', '')

LDAP_USER_FIRST_NAME_ATTR = getattr(seahub_settings, 'LDAP_USER_FIRST_NAME_ATTR', '')
LDAP_USER_LAST_NAME_ATTR = getattr(seahub_settings, 'LDAP_USER_LAST_NAME_ATTR', '')
LDAP_USER_NAME_REVERSE = getattr(seahub_settings, 'LDAP_USER_NAME_REVERSE', False)
LDAP_FILTER = getattr(seahub_settings, 'LDAP_FILTER', '')
LDAP_CONTACT_EMAIL_ATTR = getattr(seahub_settings, 'LDAP_CONTACT_EMAIL_ATTR', '')
LDAP_USER_ROLE_ATTR = getattr(seahub_settings, 'LDAP_USER_ROLE_ATTR', '')
ENABLE_SASL = getattr(seahub_settings, 'ENABLE_SASL', False)
SASL_MECHANISM = getattr(seahub_settings, 'SASL_MECHANISM', '')
SASL_AUTHC_ID_ATTR = getattr(seahub_settings, 'SASL_AUTHC_ID_ATTR', '')

# multi ldap
ENABLE_MULTI_LDAP = getattr(seahub_settings, 'ENABLE_MULTI_LDAP', False)
MULTI_LDAP_1_SERVER_URL = getattr(seahub_settings, 'MULTI_LDAP_1_SERVER_URL', '')
MULTI_LDAP_1_BASE_DN = getattr(seahub_settings, 'MULTI_LDAP_1_BASE_DN', '')
MULTI_LDAP_1_ADMIN_DN = getattr(seahub_settings, 'MULTI_LDAP_1_ADMIN_DN', '')
MULTI_LDAP_1_ADMIN_PASSWORD = getattr(seahub_settings, 'MULTI_LDAP_1_ADMIN_PASSWORD', '')
MULTI_LDAP_1_LOGIN_ATTR = getattr(seahub_settings, 'MULTI_LDAP_1_LOGIN_ATTR', '')

MULTI_LDAP_1_PROVIDER = getattr(seahub_settings, 'MULTI_LDAP_1_PROVIDER', 'ldap1')
MULTI_LDAP_1_FILTER = getattr(seahub_settings, 'MULTI_LDAP_1_FILTER', '')
MULTI_LDAP_1_CONTACT_EMAIL_ATTR = getattr(seahub_settings, 'MULTI_LDAP_1_CONTACT_EMAIL_ATTR', '')
MULTI_LDAP_1_USER_ROLE_ATTR = getattr(seahub_settings, 'MULTI_LDAP_1_USER_ROLE_ATTR', '')
MULTI_LDAP_1_ENABLE_SASL = getattr(seahub_settings, 'MULTI_LDAP_1_ENABLE_SASL', False)
MULTI_LDAP_1_SASL_MECHANISM = getattr(seahub_settings, 'MULTI_LDAP_1_SASL_MECHANISM', '')
MULTI_LDAP_1_SASL_AUTHC_ID_ATTR = getattr(seahub_settings, 'MULTI_LDAP_1_SASL_AUTHC_ID_ATTR', '')


_logger = util.get_module_logger(__name__)


def _load_path_from_env(key, check=True):
    v = os.environ.get(key, '')
    if not v:
        if check:
            raise ImportError(
                "seaf_util cannot be imported, because environment variable %s is undefined." % key)
        else:
            return None
    return os.path.normpath(os.path.expanduser(v))


CCNET_CONF_DIR = _load_path_from_env('CCNET_CONF_DIR')
SEAFILE_CONF_DIR = _load_path_from_env('SEAFILE_CONF_DIR')
SEAFILE_CENTRAL_CONF_DIR = _load_path_from_env(
    'SEAFILE_CENTRAL_CONF_DIR', check=False)

_multi_tenancy_enabled = None


def multi_tenancy_enabled():
    global _multi_tenancy_enabled
    if _multi_tenancy_enabled is None:
        _multi_tenancy_enabled = False
        try:
            cp = configparser.ConfigParser()
            cp.read(
                os.path.join(SEAFILE_CENTRAL_CONF_DIR if SEAFILE_CENTRAL_CONF_DIR else SEAFILE_CONF_DIR, 'seafile.conf'))
            if cp.has_option('general', 'multi_tenancy'):
                _multi_tenancy_enabled = cp.getboolean(
                    'general', 'multi_tenancy')
        except Exception:
            _logger.exception('failed to read multi_tenancy')
    return _multi_tenancy_enabled


# The following code was copied from https://github.com/haiwen/seahub/blob/master/seahub/base/accounts.py#L869.
# in order to keep the LDAP user password verification logic consistent, no significant changes were made.
def parse_ldap_res(ldap_search_result, enable_sasl, sasl_mechanism, sasl_authc_id_attr, contact_email_attr, role_attr):
    first_name = ''
    last_name = ''
    contact_email = ''
    user_role = ''
    authc_id = ''
    dn = ldap_search_result[0][0]
    first_name_list = ldap_search_result[0][1].get(LDAP_USER_FIRST_NAME_ATTR, [])
    last_name_list = ldap_search_result[0][1].get(LDAP_USER_LAST_NAME_ATTR, [])
    contact_email_list = ldap_search_result[0][1].get(contact_email_attr, [])
    user_role_list = ldap_search_result[0][1].get(role_attr, [])
    authc_id_list = list()
    if enable_sasl and sasl_mechanism:
        authc_id_list = ldap_search_result[0][1].get(sasl_authc_id_attr, [])

    if first_name_list:
        first_name = first_name_list[0].decode()
    if last_name_list:
        last_name = last_name_list[0].decode()

    if LDAP_USER_NAME_REVERSE:
        nickname = last_name + ' ' + first_name
    else:
        nickname = first_name + ' ' + last_name

    if contact_email_list:
        contact_email = contact_email_list[0].decode()

    if user_role_list:
        user_role = user_role_list[0].decode()

    if authc_id_list:
        authc_id = authc_id_list[0].decode()

    return dn, nickname, contact_email, user_role, authc_id


class CustomLDAPBackend(object):
    """ A custom LDAP authentication backend """

    def ldap_bind(self, server_url, dn, authc_id, password, enable_sasl, sasl_mechanism):
        bind_conn = ldap.initialize(server_url)

        try:
            bind_conn.set_option(ldap.OPT_REFERRALS, 0)
        except Exception as e:
            raise Exception('Failed to set referrals option: %s' % e)

        try:
            bind_conn.protocol_version = ldap.VERSION3
            if enable_sasl and sasl_mechanism:
                sasl_cb_value_dict = {}
                if sasl_mechanism != 'EXTERNAL' and sasl_mechanism != 'GSSAPI':
                    sasl_cb_value_dict = {
                        sasl.CB_AUTHNAME: authc_id,
                        sasl.CB_PASS: password,
                    }
                sasl_auth = sasl.sasl(sasl_cb_value_dict, sasl_mechanism)
                bind_conn.sasl_interactive_bind_s('', sasl_auth)
            else:
                bind_conn.simple_bind_s(dn, password)
        except Exception as e:
            raise Exception('ldap bind failed: %s' % e)

        return bind_conn

    def search_user(self, server_url, admin_dn, admin_password, enable_sasl, sasl_mechanism,
                    sasl_authc_id_attr, base_dn, login_attr_conf, login_attr, password, serch_filter,
                    contact_email_attr, role_attr):
        try:
            admin_bind = self.ldap_bind(server_url, admin_dn, admin_dn, admin_password, enable_sasl, sasl_mechanism)
        except Exception as e:
            raise Exception(e)

        filterstr = filter.filter_format(f'(&({login_attr_conf}=%s))', [login_attr])
        if serch_filter:
            filterstr = filterstr[:-1] + '(' + serch_filter + '))'

        result_data = None
        base_list = base_dn.split(';')
        for base in base_list:
            if base == '':
                continue
            try:
                result_data = admin_bind.search_s(base, ldap.SCOPE_SUBTREE, filterstr)
                if result_data is not None:
                    break
            except Exception as e:
                raise Exception('ldap user search failed: %s' % e)

        # user not found in ldap
        if not result_data:
            raise Exception('ldap user %s not found.' % login_attr)

        # delete old ldap bind_conn instance and create new, if not, some err will occur
        admin_bind.unbind_s()
        del admin_bind

        try:
            dn, nickname, contact_email, user_role, authc_id = parse_ldap_res(
                result_data, enable_sasl, sasl_mechanism, sasl_authc_id_attr, contact_email_attr, role_attr)
        except Exception as e:
            raise Exception('parse ldap result failed: %s' % e)

        try:
            user_bind = self.ldap_bind(server_url, dn, authc_id, password, enable_sasl, sasl_mechanism)
        except Exception as e:
            raise Exception(e)

        user_bind.unbind_s()
        return nickname, contact_email, user_role

    def authenticate(self, ldap_user=None, password=None):
        if not ENABLE_LDAP:
            return

        login_attr = ldap_user
        # search user from ldap server
        try:
            nickname, contact_email, user_role = self.search_user(
                LDAP_SERVER_URL, LDAP_ADMIN_DN, LDAP_ADMIN_PASSWORD, ENABLE_SASL, SASL_MECHANISM,
                SASL_AUTHC_ID_ATTR, LDAP_BASE_DN, LDAP_LOGIN_ATTR, login_attr, password, LDAP_FILTER,
                LDAP_CONTACT_EMAIL_ATTR, LDAP_USER_ROLE_ATTR)
        except Exception as e:
            if ENABLE_MULTI_LDAP:
                try:
                    nickname, contact_email, user_role = self.search_user(
                        MULTI_LDAP_1_SERVER_URL, MULTI_LDAP_1_ADMIN_DN, MULTI_LDAP_1_ADMIN_PASSWORD,
                        MULTI_LDAP_1_ENABLE_SASL, MULTI_LDAP_1_SASL_MECHANISM, MULTI_LDAP_1_SASL_AUTHC_ID_ATTR,
                        MULTI_LDAP_1_BASE_DN, MULTI_LDAP_1_LOGIN_ATTR, login_attr, password, MULTI_LDAP_1_FILTER,
                        MULTI_LDAP_1_CONTACT_EMAIL_ATTR, MULTI_LDAP_1_USER_ROLE_ATTR)
                except Exception as e:
                    _logger.error(e)
                    return False
            else:
                _logger.error(e)
                return False

        return True
