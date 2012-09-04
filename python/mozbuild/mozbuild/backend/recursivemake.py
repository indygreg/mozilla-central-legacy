# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from .base import BackendBase
from ..frontend.data import DirectoryTraversal

class RecursiveMakeBackend(BackendBase):
    """Backend that integrates with the existing recursive make build system.

    This backend facilitates the transition from Makefile.in to mozbuild files.

    This backend writes out .mk files alongside substituted Makefile.in files
    into the object directory. Both are consumed by a recursive make builder.

    This backend may eventually evolve to write out non-recursive make files.
    However, as long as there are Makefile.in files in the tree, we are tied to
    recursive make and thus will need this backend.
    """

    def consume(self, objs):
        """Write out build files necessary to build with recursive make."""

        for obj in objs:
            if isinstance(obj, DirectoryTraversal):
                self._process_directory_traversal(obj)

    def _process_directory_traversal(self, o):
        """Process a data.DirectoryTraversal instance.

        Each DirectoryTraversal instance results in a .mk file being written
        in the object directory. This .mk file defines variables like DIRS and
        PARALLEL_DIRS. This file is imported at the top of rules.mk
        automatically. These variables influence the build like they have for
        years.
        """

        out_path = os.path.join(o.objdir, 'dirs.mk')
        print out_path
