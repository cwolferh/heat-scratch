#
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""CLI interface for heat management."""

import sys

from oslo_config import cfg
from oslo_log import log
from six import moves

from heat.common import context
from heat.common import exception
from heat.common.i18n import _
from heat.common import messaging
from heat.common import service_utils
from heat.db import api as db_api
from heat.db import utils
from heat.db.sqlalchemy import models
from heat.objects import service as service_objects
from heat.rpc import client as rpc_client
from heat import version


CONF = cfg.CONF


def do_db_version():
    """Print database's current migration level."""
    print(db_api.db_version(db_api.get_engine()))


def do_db_sync():
    """Place a database under migration control and upgrade.

    Creating first if necessary.
    """
    db_api.db_sync(db_api.get_engine(), CONF.command.version)


class ServiceManageCommand(object):
    def service_list(self):
        ctxt = context.get_admin_context()
        services = [service_utils.format_service(service)
                    for service in service_objects.Service.get_all(ctxt)]

        print_format = "%-16s %-16s %-36s %-10s %-10s %-10s %-10s"
        print(print_format % (_('Hostname'),
                              _('Binary'),
                              _('Engine_Id'),
                              _('Host'),
                              _('Topic'),
                              _('Status'),
                              _('Updated At')))

        for svc in services:
            print(print_format % (svc['hostname'],
                                  svc['binary'],
                                  svc['engine_id'],
                                  svc['host'],
                                  svc['topic'],
                                  svc['status'],
                                  svc['updated_at']))

    def service_clean(self):
        ctxt = context.get_admin_context()
        for service in service_objects.Service.get_all(ctxt):
            svc = service_utils.format_service(service)
            if svc['status'] == 'down':
                service_objects.Service.delete(ctxt, svc['id'])
        print(_('Dead engines are removed.'))

    @staticmethod
    def add_service_parsers(subparsers):
        service_parser = subparsers.add_parser('service')
        service_parser.set_defaults(command_object=ServiceManageCommand)
        service_subparsers = service_parser.add_subparsers(dest='action')
        list_parser = service_subparsers.add_parser('list')
        list_parser.set_defaults(func=ServiceManageCommand().service_list)
        remove_parser = service_subparsers.add_parser('clean')
        remove_parser.set_defaults(func=ServiceManageCommand().service_clean)


def raw_template_get_all(context):
    from heat.db.sqlalchemy import api as sdb_api
    stacks = sdb_api.soft_delete_aware_query(context, models.Stack)
    template_ids = [stack.raw_template_id for stack in stacks]
    results = context.session.query(
        models.RawTemplate).filter(
            models.RawTemplate.id.in_(template_ids)).all()
    if not results:
        raise exception.NotFound(_('raw templates not found'))
    return results


def do_investigate():
    import json
    ctxt = context.get_admin_context()
    data = raw_template_get_all(ctxt)

    def add_to_dict(d, s):
        if s in d:
            d[s] += 1
        else:
            d[s] = 0

    def diff_dicts(d1, d2):
        allkeys = set(d1.keys())
        allkeys.update(d2.keys())
        common_keys = 0
        for k in sorted(allkeys):
            if k in d1 and k not in d2:
                print(" %s not in d2" % str(k))
            elif k not in d1 and k in d2:
                print(" %s not in d1" % str(k))
            elif d1[k] != d2[k]:
                v1 = str(d1[k])
                v2 = str(d2[k])
                if len(v1) > 68:
                    v1 = v1[:68]+' <snip>'
                if len(v2) > 68:
                    v2 = v2[:68]+' <snip>'
                print(" -%s:%s" % (k, d1[k]))
                print(" +%s:%s" % (k, d2[k]))
            else:
                common_keys += 1
        print("common_keys: %d" % (common_keys))

    resource_registries = {}
    param_defaults = {}
    template_id_to_resource_registry = {}
    count = 0
    for rt in data:
        count += 1
        rreg_json = json.dumps(
            rt.environment['resource_registry'], 
            sort_keys=True)
        template_id_to_resource_registry[rt.id] = \
            rt.environment['resource_registry']
        add_to_dict(resource_registries, rreg_json)
        add_to_dict(param_defaults,
                    json.dumps(
                        rt.environment['parameter_defaults'],
                        sort_keys=True))
    print("%d raw_template rows" % count)
    print("raw_template.environment has "
          "%d distinct 'resource_registry's" 
          % (len(resource_registries)))
    print("raw_template.environment has "
          "%d distinct 'parameter_defaults'" 
          % (len(param_defaults)))
    print("raw_template.environment parameter_defaults_lengths: "+
           ','.join([str(len(p)) for p in param_defaults]))
    print("raw_template.environment resource_registry lengths: "+
           ','.join([str(len(p)) for p in resource_registries]))
    #print("diff of parameter_defaults")
    #(p1, c) = param_defaults.popitem()
    #(p2, c) = param_defaults.popitem()
    # sudo easy_install datadiff
    #import datadiff
    #print datadiff.diff(json.loads(p1), json.loads(p2))
    
    template_ids = sorted(template_id_to_resource_registry.keys())
    for i in range(len(template_ids)-1):
        tid1 = template_ids[i]
        tid2 = template_ids[i+1]
        print('diff of raw_template_id %d and %d' % (tid1, tid2))
        diff_dicts(
            template_id_to_resource_registry[tid1],
            template_id_to_resource_registry[tid2])
    #diff_dicts(
    #    template_id_to_resource_registry[756],
    #    template_id_to_resource_registry[755])


def do_resource_data_list():
    ctxt = context.get_admin_context()
    data = db_api.resource_data_get_all(ctxt, CONF.command.resource_id)

    print_format = "%-16s %-64s"

    for k in data.keys():
        print(print_format % (k, data[k]))


def do_reset_stack_status():
    print(_("Warning: this command is potentially destructive and only "
            "intended to recover from specific crashes."))
    print(_("It is advised to shutdown all Heat engines beforehand."))
    print(_("Continue ? [y/N]"))
    data = moves.input()
    if not data.lower().startswith('y'):
        return
    ctxt = context.get_admin_context()
    db_api.reset_stack_status(ctxt, CONF.command.stack_id)


def do_migrate():
    messaging.setup()
    client = rpc_client.EngineClient()
    ctxt = context.get_admin_context()
    try:
        client.migrate_convergence_1(ctxt, CONF.command.stack_id)
    except exception.NotFound:
        raise Exception(_("Stack with id %s can not be found.")
                        % CONF.command.stack_id)
    except exception.ActionInProgress:
        raise Exception(_("The stack or some of its nested stacks are "
                          "in progress. Note, that all the stacks should be "
                          "in COMPLETE state in order to be migrated."))


def purge_deleted():
    """Remove database records that have been previously soft deleted."""
    utils.purge_deleted(CONF.command.age,
                        CONF.command.granularity,
                        CONF.command.project_id)


def do_crypt_parameters_and_properties():
    """Encrypt/decrypt hidden parameters and resource properties data."""
    ctxt = context.get_admin_context()
    prev_encryption_key = CONF.command.previous_encryption_key
    if CONF.command.crypt_operation == "encrypt":
        utils.encrypt_parameters_and_properties(
            ctxt, prev_encryption_key, CONF.command.verbose_update_params)
    elif CONF.command.crypt_operation == "decrypt":
        utils.decrypt_parameters_and_properties(
            ctxt, prev_encryption_key, CONF.command.verbose_update_params)


def add_command_parsers(subparsers):
    # one-off investigation
    parser = subparsers.add_parser('investigate')
    parser.set_defaults(func=do_investigate)

    # db_version parser
    parser = subparsers.add_parser('db_version')
    parser.set_defaults(func=do_db_version)

    # db_sync parser
    parser = subparsers.add_parser('db_sync')
    parser.set_defaults(func=do_db_sync)
    # positional parameter, can be skipped. default=None
    parser.add_argument('version', nargs='?')

    # migrate-stacks parser
    parser = subparsers.add_parser('migrate-convergence-1')
    parser.set_defaults(func=do_migrate)
    parser.add_argument('stack_id')

    # purge_deleted parser
    parser = subparsers.add_parser('purge_deleted')
    parser.set_defaults(func=purge_deleted)
    # positional parameter, can be skipped. default='90'
    parser.add_argument('age', nargs='?', default='90',
                        help=_('How long to preserve deleted data.'))
    # optional parameter, can be skipped. default='days'
    parser.add_argument(
        '-g', '--granularity', default='days',
        choices=['days', 'hours', 'minutes', 'seconds'],
        help=_('Granularity to use for age argument, defaults to days.'))
    # optional parameter, can be skipped.
    parser.add_argument(
        '-p', '--project-id',
        help=_('Project ID to purge deleted stacks.'))
    # update_params parser
    parser = subparsers.add_parser('update_params')
    parser.set_defaults(func=do_crypt_parameters_and_properties)
    # positional parameter, can't be skipped
    parser.add_argument('crypt_operation',
                        choices=['encrypt', 'decrypt'],
                        help=_('Valid values are encrypt or decrypt. The '
                               'heat-engine processes must be stopped to use '
                               'this.'))
    # positional parameter, can be skipped. default=None
    parser.add_argument('previous_encryption_key',
                        nargs='?',
                        default=None,
                        help=_('Provide old encryption key. New encryption'
                               ' key would be used from config file.'))
    parser.add_argument('--verbose-update-params', action='store_true',
                        help=_('Print an INFO message when processing of each '
                               'raw_template or resource begins or ends'))

    parser = subparsers.add_parser('resource_data_list')
    parser.set_defaults(func=do_resource_data_list)
    parser.add_argument('resource_id',
                        help=_('Stack resource id'))

    parser = subparsers.add_parser('reset_stack_status')
    parser.set_defaults(func=do_reset_stack_status)
    parser.add_argument('stack_id',
                        help=_('Stack id'))

    ServiceManageCommand.add_service_parsers(subparsers)

command_opt = cfg.SubCommandOpt('command',
                                title='Commands',
                                help=_('Show available commands.'),
                                handler=add_command_parsers)


def main():
    log.register_options(CONF)
    log.setup(CONF, "heat-manage")
    CONF.register_cli_opt(command_opt)
    try:
        default_config_files = cfg.find_config_files('heat', 'heat-engine')
        CONF(sys.argv[1:], project='heat', prog='heat-manage',
             version=version.version_info.version_string(),
             default_config_files=default_config_files)
    except RuntimeError as e:
        sys.exit("ERROR: %s" % e)

    try:
        CONF.command.func()
    except Exception as e:
        sys.exit("ERROR: %s" % e)
