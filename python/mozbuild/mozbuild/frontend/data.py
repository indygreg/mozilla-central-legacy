# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

r"""Data structures representing the build config.

The build frontend files are parsed into static data structures. These data
structures are defined in this module.

All data structures of interest are children of the BuildObject class.

Logic for populating these data structures is not defined in this class.
Instead, what we have here are dumb container classes. The emitter module
contains the code for converting executed mozbuild files into these data
structures.
"""

from collections import OrderedDict

class BuildObject(object):
    """Base class for all build objects.

    Holds common properties shared by all function-specific build objects.
    """

    __slots__ = (
        'reldir',
        'srcdir',
        'topsrcdir',
    )

    def __init__(self, sandbox):
        self.topsrcdir = sandbox['TOPSRCDIR']
        #self.reldir = sandbox['RELDIR']
        #self.srcdir = sandbox['SRCDIR']

class DirectoryTraversal(BuildObject):
    """Describes how directory traversal for building should work.

    This build object is likely only of interest to the recursive make backend.
    Other build backends should (ideally) not attempt to mimic the behavior of
    the recursive make backend. The only reason this exists is to support the
    existing recursive make backend while the transition to mozbuild frontend
    files is complete.

    Fields in this class correspond to similarly named variables in the
    frontend files.
    """
    __slots__ = (
        'dirs',
        'parallel_dirs',
        'tool_dirs',
        'test_dirs',
        'test_tool_dirs',
        'tier_dirs',
        'tier_static_dirs',
    )

    def __init__(self, sandbox):
        BuildObject.__init__(self, sandbox)

        self.dirs = []
        self.parallel_dirs = []
        self.tool_dirs = []
        self.test_dirs = []
        self.test_tool_dirs = []
        self.tier_dirs = OrderedDict()
        self.tier_static_dirs = OrderedDict()
