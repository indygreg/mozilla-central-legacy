# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from .base import BuildBackend
from ..frontend.data import DirectoryTraversal

class RecursiveMakeBackend(BuildBackend):
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

        if not os.path.exists(o.objdir):
            os.makedirs(o.objdir)

        # We always generate an output file because we want the build system to
        # fail if this dependent file is missing because a missing file could
        # mean the build wasn't properly configured and we want to catch that.

        with open(out_path, 'w') as fh:
            print >>fh, '# THIS FILE WAS AUTOMATICALLY GENERATED. DO NOT EDIT.'

            for tier, dirs in o.tier_dirs.iteritems():
                print >>fh, 'TIERS += %s' % tier

                if len(dirs):
                    print >>fh, 'tier_%s_dirs += %s' % (tier, ' '.join(dirs))

                # tier_static_dirs should have the same keys as tier_dirs.
                if len(o.tier_static_dirs[tier]):
                    print >>fh, 'tier_%s_staticdirs += %s' % (
                        tier, ' '.join(o.tier_static_dirs[tier]))

            if len(o.dirs):
                print >>fh, 'DIRS := %s' % ' '.join(o.dirs)

            if len(o.parallel_dirs):
                print >>fh, 'PARALLEL_DIRS := %s' % ' '.join(o.parallel_dirs)

            if len(o.tool_dirs):
                print >>fh, 'TOOL_DIRS := %s' % ' '.join(o.tool_dirs)

            if len(o.test_dirs):
                print >>fh, 'TEST_DIRS := %s' % ' '.join(o.test_dirs)

            if len(o.test_tool_dirs):
                print >>fh, 'ifdef ENABLE_TESTS'
                print >>fh, 'TOOL_DIRS += %s' % ' '.join(o.test_tool_dirs)
                print >>fh, 'endif'
