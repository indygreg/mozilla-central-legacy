# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import json
import os.path

from mozbuild.base import Base
from mozbuild.backend.legacy import LegacyBackend
from mozbuild.backend.hybridmake import HybridMakeBackend
from mozbuild.backend.visualstudio import VisualStudioBackend
from mozbuild.frontend.frontend import BuildFrontend
from mozbuild.util import hash_file

class BackendManager(Base):
    def __init__(self, settings, log_manager):
        Base.__init__(self, settings, log_manager)

        self.frontend = self._spawn(BuildFrontend)
        #self.frontend.load_input_files_from_root_makefile()
        self.frontend.load_autoconf_input_files()

        self.backend = None

        self._ensure_objdir_exists()

    def set_backend(self, name):
        if name == 'legacy':
            self.backend = LegacyBackend(self.frontend)
        elif name == 'reformat':
            self.backend = LegacyBackend(self.frontend)
            self.backend.reformat = True
            self.backend.verify_reformat = True
        elif name == 'hybridmake':
            self.backend = HybridMakeBackend(self.frontend)
        elif name == 'visualstudio':
            self.backend = VisualStudioBackend(self.frontend)
        else:
            raise Exception('Unknown backend: %s' % name)

    def ensure_generate(self):
        """Ensure the backend generation is up to date.

        If any source files have changed or if generation has never been
        run, a generation will be performed.
        """
        assert self.backend is not None

        state = self.load_state()

        # No state means we haven't done any generation.
        if state is None:
            self.log(logging.INFO, 'backend_generate_reason',
                {'reason': 'no_state'},
                'Generating backend config because no state.')
            self.generate()
            return

        required_paths = set()
        required_hashes = {}

        for path, old_hash in state['frontend'].iteritems():
            required_paths.add(path)
            required_hashes[path] = old_hash

        for path in state['backend']['output_directories']:
            required_paths.add(path)

        for path, old_hash in state['backend']['output_files'].iteritems():
            required_paths.add(path)
            required_hashes[path] = old_hash

        for path in required_paths:
            if os.path.exists(path):
                continue

            self.log(logging.INFO, 'backend_generate_reason',
                {'reason': 'path_no_exist', 'path': path},
                'Generating backend config because path does not exist: {path}')
            self.generate()
            return

        for path, old_hash in required_hashes.iteritems():
            new_hash = hash_file(path)

            if new_hash == old_hash:
                continue

            self.log(logging.INFO, 'backend_generate_reason',
                {'reason': 'path_changed', 'path': path},
                'Generating backend config because path changed: {path}')

            self.generate()
            return

    def generate(self):
        assert self.backend is not None

        self.backend.generate()

        self.save_state()

    def build(self):
        self.ensure_generate()

        self.backend.build()

    def save_state(self):
        state = {
            'frontend': {

            },
            'backend': {
                'output_directories': list(self.backend.output_directories),
                'output_files': {},
            },
        }

        for path in self.frontend.input_files:
            assert os.path.isabs(path)

            state['frontend'][path] = hash_file(path)

        for path in self.backend.output_files.iterkeys():
            state['backend']['output_files'][path] = hash_file(path)

        path = self._get_state_filename('backend.json')

        with open(path, 'wb') as fh:
            json.dump(state, fh, indent=2)

    def load_state(self):
        path = self._get_state_filename('backend.json')

        if not os.path.isfile(path):
            return None

        with open(path, 'rb') as fh:
            return json.load(fh)
