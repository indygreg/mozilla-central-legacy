# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os.path

from mozbuild.base import Base
from mozbuild.backend.legacy import LegacyBackend
from mozbuild.backend.hybridmake import HybridMakeBackend
from mozbuild.frontend.frontend import BuildFrontend
from mozbuild.util import hash_file

class BackendManager(Base):
    def __init__(self, config):
        Base.__init__(self, config)

        self.frontend = BuildFrontend(config)
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
            self.generate()
            return

        # If any of the frontend files changed, we need to regenerate.
        frontend_changed = False

        for path, old_hash in state['frontend'].iteritems():
            if not os.path.exists(path):
                frontend_changed = True
                break

            if hash_file(path) != old_hash:
                frontend_changed = True
                break

        if frontend_changed:
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

            }
        }

        for path in self.frontend.input_files:
            assert os.path.isabs(path)

            state['frontend'][path] = hash_file(path)

        path = self._get_state_filename('backend.json')

        with open(path, 'wb') as fh:
            json.dump(state, fh, indent=2)

    def load_state(self):
        path = self._get_state_filename('backend.json')

        if not os.path.isfile(path):
            return None

        with open(path, 'rb') as fh:
            return json.load(fh)
