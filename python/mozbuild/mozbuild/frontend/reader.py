# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains code for reading metadata from the build system into
# data structures.

import os
import sys

class ReadOnlyDict(object):
    def __init__(self, d):
        self._dict = d

    def __len__(self):
        return len(self._dict)

    def __getattribute__(self, k):
        return object.__getattribute__(self, '_dict').get(k, None)

    def __getitem__(self, k):
        return self._dict[k]

    def __iter__(self):
        return iter(self._dict)

class Sandbox(object):
    """Represents a sandbox for executing a mozbuild config file.

    All functionality available to mozconfig config files is present in
    this class.
    """
    def __init__(self, config):
        """Initialize an empty sandbox associated with a build configuration.

        The passed in config is the output of configure. All sandboxes have
        access its global data.
        """
        self.config = config
        self._locals = {}
        self._tiers = {}
        self._populate_globals()

    def exec_file(self, path):
        """Execute code at a path in the sandbox."""
        source = None

        with open(path, 'r') as fd:
            # compile() needs a newline on Python < 2.7.
            source = fd.read() + '\n'

        old_write_bytecode = sys.dont_write_bytecode

        try:
            # We don't want Python bytecode files polluting the tree.
            # TODO change location of bytecode files so parsing can be
            # cached, which may result in a speed-up.
            sys.dont_write_bytecode = True
            code = compile(source, path, 'exec')

            exec code in self._globals, self._locals

            # TODO catch accesses to invalid names and print a helpful
            # error message, possibly with links to docs.
        finally:
            sys.dont_write_bytecode = old_write_bytecode

    @property
    def result(self):
        """Obtain the result of the sandbox.

        This is a data structure with the raw results from execution.
        """
        IGNORE_GLOBALS = ['__builtins__', 'CONFIG']

        g = {}
        for k, v in self._globals.iteritems():
            if k in IGNORE_GLOBALS:
                continue

            g[k] = v

        return {
            'globals': g,
            'locals': self._locals,
        }

    def _add_tier_directory(self, tier, reldir, static=False):
        """Register a tier directory with the build."""
        if isinstance(reldir, basestring):
            reldir = [reldir]

        if not tier in self._tiers:
            self._tiers[tier] = {
                'regular': [],
                'static': [],
            }

        key = 'regular'
        if static:
            key = 'static'

        for path in reldir:
            if path in self._tiers[tier][key]:
                continue

            self._tiers[tier][key].append(path)

    def _include(self, path):
        """Include and exec another file within the context of this one."""

        # Security isn't a big deal since this all runs locally. But, as a
        # basic precaution, we limit access to files in the tree of the top
        # source directory.
        normpath = os.path.normpath(os.path.realpath(path))
        normtop = os.path.normpath(os.path.realpath(self.config['topsrcdir']))

        if not normpath.startswith(normtop):
            raise Exception('Included files must be under top source '
                'directory');

        self.exec_file(path)

    def _populate_globals(self):
        """Set up the initial globals environment for the sandbox.

        This defines what the sandbox has access to. We make available
        specific variables, functions, etc.
        """

        self._globals = {
            '__builtins__': {
                # Basic constants.
                'None': None,
                'False': False,
                'True': True,
            },

            # Pre-defined variables.
            'CONFIG': ReadOnlyDict(self.config),

            'DIRS': list(),
            'PARALLEL_DIRS': list(),
            'TEST_DIRS': list(),
            'GARBAGE_DIRS': list(),

            # Special functions.
            'add_tier_dir': self._add_tier_directory,
            'include': self._include,
        }


class BuildReader(object):
    """Read a tree of mozbuild files into a data structure.

    This is where the build system starts. You give it a top source directory
    and a configuration for the tree (the output of configure) and it parses
    the build.mozbuild files and collects the data they define.
    """

    def __init__(self, config):
        self.config = config
        self.topsrcdir = config['topsrcdir']

    def read(self):
        # We start in the root directory and descend according to what we find.
        path = os.path.join(self.topsrcdir, 'build.mozbuild')

        self.read_mozbuild(path)

    def read_mozbuild(self, path):
        print 'Reading %s' % path
        sandbox = Sandbox(self.config)
        sandbox.exec_file(path)

        result = sandbox.result

        # Traverse into referenced files.

        # We first collect directories populated in variables.
        dir_vars = ['DIRS', 'PARALLEL_DIRS']

        if self.config.get('ENABLE_TESTS', False):
            dir_vars += ['TEST_DIRS']

        dirs = set()
        for var in dir_vars:
            dirs |= set(result['globals'][var])

        # We also have tiers whose members are directories.
        for tier, values in self._tiers.iteritems():
            dirs |= set(values['regular'])
            dirs |= set(values['static'])

        curdir = os.path.dirname(path)
        for relpath in dirs:
            self.read_mozbuild(os.path.join(curdir, relpath, 'build.mozbuild'))
