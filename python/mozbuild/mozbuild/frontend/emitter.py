# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from .data import DirectoryTraversal

class BuildDefinitionEmitter(object):
    """Converts read frontend files into data structures.

    This is a bridge between reader.py and data.py. It takes what was read by
    reader.py and converts it into the classes defined in data.py.
    """

    DIRECTORY_TRAVERSAL_VARIABLES = ['DIRS', 'PARALLEL_DIRS', 'TOOL_DIRS',
        'TEST_DIRS', 'TEST_TOOL_DIRS', 'TIERS']

    def __init__(self, config):
        pass

    def emit_from_sandboxes(self, sandboxes):
        """Convert an iterable of Sandbox into build objects.

        This is a convenience method that loops over all Sandbox instances
        and calls emit_from_sandbox. It does nothing more.
        """
        for sandbox in sandboxes:
            for o in self.emit_from_sandbox(sandbox):
                yield o

    def emit_from_sandbox(self, sandbox):
        """Convert a Sandbox to build objects.

        This takes a Sandbox (that has presumably executed a mozbuild file)
        and converts the results into build data objects.

        This is a generator of mozbuild.frontend.data.BuildObject instances.
        Each emitted instance will be a child class of BuildObject.
        """
        o = DirectoryTraversal(sandbox)
        o.dirs = sandbox.get('DIRS', [])
        o.parallel_dirs = sandbox.get('PARALLEL_DIRS', [])
        o.tool_dirs = sandbox.get('TOOL_DIRS', [])
        o.test_dirs = sandbox.get('TEST_DIRS', [])
        o.test_tool_dirs = sandbox.get('TEST_TOOL_DIRS', [])

        if 'TIERS' in sandbox:
            for tier in sandbox['TIERS']:
                o.tier_dirs[tier] = sandbox['TIERS'][tier]['regular']
                o.tier_static_dirs[tier] = sandbox['TIERS'][tier]['static']

        yield o


