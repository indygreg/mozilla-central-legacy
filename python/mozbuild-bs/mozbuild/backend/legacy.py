# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from mozbuild.buildconfig.backend.base import BackendBase
from mozbuild.buildconfig.backend.utils import makefile_output_path
from mozbuild.buildconfig.backend.utils import substitute_makefile

class LegacyBackend(BackendBase):
    """The "legacy" build backend.

    This build backend is what Mozilla has used for years. It is non-recursive
    make invoked by evaluating the default target on the Makefile in the
    top-level directory in the object directory.
    """
    def __init__(self, *args):
        BackendBase.__init__(self, *args)

        self.reformat = False
        self.strip_false_conditionals = False
        self.verify_reformat = False

    @property
    def makefiles(self):
        """Generator for converted Makefile instances."""
        for makefile in self.frontend.makefiles.makefiles():
            substitute_makefile(makefile, self.frontend)
            yield makefile

    ############################
    # Generation functionality #
    ############################

    def _generate(self):
        for makefile in self.makefiles:
            self._write_output_makefile(makefile)

    def _write_output_makefile(self, makefile):
        output_path = makefile_output_path(self.srcdir, self.objdir, makefile)
        output_dir = os.path.dirname(output_path)

        self.mkdir(output_dir)

        with open(output_path, 'w') as fh:
            # This is hacky and need until makefile.py uses pymake's API.
            if self.reformat:
                from pymake.parser import parsestring

                source = '\n'.join(makefile.lines())
                statements = parsestring(source, output_path)
                print >>fh, statements.to_source()

                # TODO verify rewrite.
            else:
                for line in makefile.lines():
                    print >>fh, line

        self.add_generate_output_file(output_path, [makefile.filename])

    ##########################
    # Building Functionality #
    ##########################

    def _build(self):
        self._run_make()

    def _clean(self):
        pass
