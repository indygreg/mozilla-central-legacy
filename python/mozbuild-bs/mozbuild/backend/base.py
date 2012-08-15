# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from mozbuild.base import Base


class BackendBase(Base):
    """Base class defining the build backend interface.

    Build backends are entities that take the configuration defining the build
    environment and translate that to something used to actually perform the
    build.

    Build backends have a generation and a build phase. The generation phase is
    called at tree configuration time and automatically if the inputs to a
    previous generation phase have changed, invalidating its output. The role
    of the generation phase is to convert the inputs to the build system into
    something that can later be used by this backend to actually build the
    tree.

    The build phase is what is used to build the tree.
    """
    def __init__(self, frontend):
        Base.__init__(self, frontend.settings, frontend.log_manager)

        self.frontend = frontend
        self.output_files = {}
        self.output_directories = set()

        self.build_phases = []

        self._listeners = []

    @property
    def state(self):
        """The state for this backend.

        Child classes must implement this. It returns an object that describes
        the state of this backend. The state is persisted and restored to and
        from disk between invocations. The returned object is pickled. So, it
        should go without saying that the object must be pickleable.
        """
        raise Exception('%s must implement state property.' % __name__)

    def generate(self):
        """Generate files, etc to support building with this backend.

        This is essentially configuration of this backend.
        """
        self._generate()

    def build(self):
        """Build the tree."""
        self._build()

    def clean(self):
        """Clean the tree.

        This cleans output from the generate phase and the build phase.
        """
        self._clean()

        for path in sorted(self.output_files.keys()):
            if not os.path.exists(path):
                continue

            print 'Removing output file: %s' % path
            os.unlink(path)

    def add_listener(self, listener):
        self._listeners.append(listener)

    def add_generate_output_file(self, output_path, dependency_paths=None):
        """Register a file as being created by the generate stage.

        The generator is expected to call this for every output file it
        creates. The input files that influence generation of that file are
        specified when calling so that changes in the input files trigger
        regeneration.
        """
        self.output_files[output_path] = {'dependencies': dependency_paths}

    def mkdir(self, directory):
        """Convenience method to create a directory."""
        if os.path.exists(directory):
            return

        os.makedirs(directory, 0777)

    def _generate(self):
        """Class-specific implementation of initial generation.

        Child classes must implement this. It gets called by generate() when a
        full generation is being required.
        """
        raise Exception('%s must implement _generate()' % __name__)

    def _regenerate(self, frontend, changed_inputs):
        """Class-specific implementation of regeneration.

        Child classes must implement this. This method gets called by
        generate() when the tree is being regenerated (it has already been
        generated once) or when files listed as dependencies for output files
        have changed.

        Child classes can choose to perform an optimal regeneration of only
        the entities impacted by changed inputs. Or, they could simply call
        _generate() to force a full regeneration. It is completely up to the
        child class.
        """
        raise Exception('%s must implement _regenerate()' % __name__)

    def _build(self):
        """Internal implementation of the build phase.

        This is called by build() when appropriate.
        """
        raise Exception('%s must implement _build()' % __name__)

    def _clean(self):
        """Internal implementation of the clean phase.

        Child classes are expected to perform custom cleaning in this method.
        After this is called, registered output from the generation phase will
        be automatically cleaned, so the child class does not need to do this
        itself.
        """
        raise Exception('%s must implement _clean()' % __name__)

    def _call_listeners(self, action, **kwargs):
        for listener in self._listeners:
            listener(action, **kwargs)
