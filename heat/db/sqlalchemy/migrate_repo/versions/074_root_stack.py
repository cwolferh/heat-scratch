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

import sqlalchemy


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    root_id = sqlalchemy.Column('root_id',
                                sqlalchemy.String(36))

    root_id.create(stack_table)
    root_idx = sqlalchemy.Index('ix_stack_root_id',
                                stack_table.c.root_id,
                                mysql_length=36)
    root_idx.create(migrate_engine)
