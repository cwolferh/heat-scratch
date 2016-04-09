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

import collections
import six
import weakref

from oslo_log import log as logging

from heat.common.i18n import _
from heat.db import api as db_api
from heat.objects import raw_template_files

LOG = logging.getLogger(__name__)

_d = weakref.WeakValueDictionary()


class ReadOnlyDict(dict):
    def __setitem__(self, key):
        raise ValueError("Attempted to write to internal TemplateFiles cache")


class TemplateFiles(collections.Mapping):

    def __init__(self, files):
        self.files = None
        self.files_id = None
        if files is None:
            return
        if isinstance(files, TemplateFiles):
            self.files_id = files.files_id
            self.files = files.files
            return
        if isinstance(files, six.integer_types):
            self.files_id = files
            if self.files_id in _d:
                self.files = _d[self.files_id]
            return
        if not isinstance(files, dict):
            raise ValueError(_('Expected dict, got %(cname)s for files, '
                               '(value is %(val)s)') %
                             {'cname': files.__class__,
                              'val': str(files)})
        # the dict has not been persisted as a raw_template_files db obj
        # yet, so no self.files_id
        self.files = ReadOnlyDict(files)

    def __getitem__(self, key):
        self._refresh_if_needed()
        if self.files is None:
            raise KeyError
        return self.files[key]

    def __setitem__(self, key, value):
        self.update({key: value})

    def __len__(self):
        self._refresh_if_needed()
        if not self.files:
            return 0
        return len(self.files)

    def __contains__(self, key):
        self._refresh_if_needed()
        if not self.files:
            return False
        return key in self.files

    def __iter__(self):
        self._refresh_if_needed()
        if self.files_id is None:
            return iter(ReadOnlyDict({}))
        return iter(self.files)

    def _refresh_if_needed(self):
        # retrieve files from db if needed
        if self.files_id is None:
            return
        if self.files_id in _d:
            self.files = _d[self.files_id]
            LOG.debug('template_files cache hit for id %d' % self.files_id)
            return
        LOG.debug('template_files cache miss for id %d' % self.files_id)
        self._refresh()

    def _refresh(self):
        rtf_obj = db_api.raw_template_files_get(None, self.files_id)
        _files_dict = ReadOnlyDict(rtf_obj.files)
        self.files = _files_dict
        _d[self.files_id] = _files_dict

    def store(self, ctxt=None):
        if not self.files:
            return
        if self.files_id is not None:
            # the only way we could have a not null file_id is if
            # the files_dict was already stored, and they are immutable.
            return
        rtf_obj = raw_template_files.RawTemplateFiles.create(
            ctxt, {'files': self.files})
        self.files_id = rtf_obj.id
        _d[self.files_id] = self.files

    def update(self, files):
        # Sets up the next call to store() to create a new
        # raw_template_files db obj. It seems like we *could* just
        # update the existing raw_template_files obj, but the problem
        # with that is other heat-engine processes' _d dictionaries
        # would have stale data for a given raw_template_files.id with
        # no way of knowing whether that data should be refreshed or
        # not. So, just avoid the potential for weird race conditions
        # and create another db obj in the next store().
        if len(files) == 0:
            return
        if not isinstance(files, dict):
            raise ValueError(_('Expected dict, got %(cname)s for files, '
                               '(value is %(val)s)') %
                             {'cname': files.__class__,
                              'val': str(files)})

        new_files = files
        self._refresh_if_needed()
        if self.files:
            new_files = self.files.copy()
            new_files.update(files)
        self.files_id = None  # not persisted yet
        self.files = ReadOnlyDict(new_files)
