# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

######################################################################
# DO NOT UPDATE THIS FILE WITHOUT SIGN-OFF FROM A BUILD MODULE PEER. #
######################################################################

r"""Defines the global config variables.

This module contains a data structure defining the global variables that have
special meaning in the frontend files for the build system.

If you are looking for the absolute authority on what variables can be defined
and what they are supposed to do, you've come to the right place.

"""

# Each variable is a tuple of:
#
#   (type, default_value, docs)
#
# This is the authoritative source of variables, so please document thoroughly.

FRONTEND_VARIABLES = {
    # Variables controlling reading of other frontend files.
    'DIRS': (list, [],
        """Child directories to descend into looking for build frontend files.

        This works similarly to the DIRS variable in make files. Each str value
        in the list is the same of a child directory. When this file is done
        parsing, the build reader will descend into each listed directory and
        read the frontend file there. If there is no frontend file, an error
        is raised.

        Values are relative paths. They can be multiple directory levels
        above or below. Use ".." for parent directories and "/" for path
        delimiters.
        """),

    'PARALLEL_DIRS': (list, [],
        """Like DIRS but build execution of these is allowed to occur in
        parallel.

        Ideally this variable does not exist. It is provided so a transition
        from recursive makefiles can be made. Once the build system has been
        converted to not use Makefile's for the build frontend, this will
        likely go away.
        """),

    'TOOL_DIRS': (list, [],
        """Like DIRS but for tools.

        Tools are for pieces of the build system that aren't required to
        produce a working binary (in theory). They provide things like test
        code and utilities.
        """),

    'TEST_DIRS': (list, [],
        """Like DIRS but only for directories that contain test-only code.

        If tests are not enabled, this variable will be ignored.

        This variable may go away once the transition away from Makefiles is
        complete.
        """),

    # Cleaning up build files.
    'GARBAGE_DIRS': (list, [],
        """Directories relative to this one that should be cleaned up as part
        of the build.

        This should ideally not be needed. Instead, build backends should
        populate this. This will only live as long as Makefile.in's still
        existing in the tree.
        """),

}
