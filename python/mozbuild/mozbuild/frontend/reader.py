# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains code for reading metadata from the build system into
# data structures.

r"""Read build frontend files into data structures.

The build system consists of frontend files call "mozbuild" files. mozbuild
files are executed and the results of the execution are assembled into data
structures representing the build system definition. This definition contains
the set of files to compile, etc.

mozbuild files are actually Python scripts. However, they are sandboxed and
executed mozbuild files can only perform limited tasks.

In terms of influencing the build, mozbuild files can only call specific
exported functions and assign to a whitelist of allowed variables. The enforced
convention is that all UPPERCASE variables are reserved. Access to these
variables goes through a whitelist and assignment is validated to ensure values
are proper. The set of global variables that can be assigned to is defined in
the mozbuild.frontend.variables module.

Assignment to all non-uppercase variables is allowed. However, these variables
do not influence the output. So, non-uppercase variables are essentially
throwaway local variables.

In terms of code architecture, the main interface is BuildReader. It starts
with a root mozbuild file. It creates a new execution environment for this
file, which is represented by the Sandbox class. The Sandbox class is what
defines what is allowed to execute in an individual mozbuild file. The Sandbox
consists of a local and global namespace, which are modeled by the
LocalNamespace and GlobalNamespace classes, respectively. The global namespace
contains all of the takeaway information from the execution. The local
namespace is for throwaway local variables and its contents are discarded after
execution.

The BuildReader contains basic logic for traversing a tree of mozbuild files.
It does this by examining specific variables populated during execution.
"""

import copy
import logging
import os
import sys

from .variables import FRONTEND_VARIABLES

# We start with some ultra-generic data structures. These should ideally be
# elsewhere. Where?

class ReadOnlyDict(dict):
    """A read-only dictionary."""
    def __init__(self, d):
        dict.__init__(self, d)

    def __setitem__(self, name, value):
        raise Exception('Object does not support assignment.')

class DefaultOnReadDict(dict):
    """A dictionary that returns default values for missing keys on read."""

    def __init__(self, d, defaults=None, global_default=(None,)):
        """Create an instance from an iterable with defaults.

        The first argument is fed into the dict constructor.

        defaults is a dict mapping keys to their default values.

        global_default is the default value for *all* missing keys. If it isn't
        specified, no default value for keys not in defaults will be used and
        IndexError will be raised on access.
        """
        dict.__init__(self, d)

        if defaults is None:
            defaults = {}

        self._defaults = defaults
        self._global_default = global_default

    def __getitem__(self, k):
        try:
            return dict.__getitem__(self, k)
        except:
            pass

        if k in self._defaults:
            dict.__setitem__(self, k, copy.deepcopy(self._defaults[k]))
        elif self._global_default != (None,):
            dict.__setitem__(self, k, copy.deepcopy(self._global_default))

        return dict.__getitem__(self, k)


class ReadOnlyDefaultDict(DefaultOnReadDict, ReadOnlyDict):
    """A read-only dictionary that supports default values on retrieval."""
    def __init__(self, d, defaults=None, global_default=(None,)):
        DefaultOnReadDict.__init__(self, d, defaults, global_default)

    def __getattr__(self, k):
        return self.__getitem__(k)


# Now we have the meat of the file.

class GlobalNamespace(dict):
    """Represents the globals namespace in a sandbox.

    This is a highly specialized dictionary employing lots of magic.

    At the crux we have the concept of a restricted keys set. Only very
    specific keys may be retrieved or mutated. The rules are as follows:

        - The '__builtins__' key is hardcoded and is read-only.
        - Some functions are registered and provided by the Sandbox.
        - Variables are provided by the FRONTEND_VARIABLES list. These
          represent the set of what can be assigned to during execution.

    When variables are assigned to, we verify assignment is allowed. Assignment
    is allowed if the variable is known (from the FRONTEND_VARIABLES list) and
    if the value being assigned is an expected type (also defined by
    FRONTEND_VARIABLES).

    When variables are read, we first try to read the existing value. If a
    value is not found and it is a known FRONTEND_VARIABLE, we return the
    default value for it. We don't assign default values until they are
    accessed because this makes debugging the end-result much simpler. Instead
    of a data structure with lots of empty/default values, you have a data
    structure with only the values that are needed.

    Callers are given a backdoor to perform any write to the object by using
    the instance inside a with statement. e.g.

        ns = GlobalNamespace()
        with ns:
            ns['foo'] = True

        ns['bar'] = True  # KeyError raised.
    """

    def __init__(self):
        dict.__init__(self, {
            '__builtins__': ReadOnlyDict({
                # Basic constants.
                'None': None,
                'False': False,
                'True': True,
            }),
        })

        self._allow_all_writes = False

    def __getitem__(self, name):
        if not isinstance(name, basestring):
            raise TypeError('Only string keys are allowed.')

        try:
            return dict.__getitem__(self, name)
        except KeyError:
            pass

        default = FRONTEND_VARIABLES.get(name, None)
        if default is None:
            raise KeyError()

        dict.__setitem__(self, name, copy.deepcopy(default[1]))
        return dict.__getitem__(self, name)

    def __setitem__(self, name, value):
        default = FRONTEND_VARIABLES.get(name, None)

        if self._allow_all_writes:
            dict.__setitem__(self, name, value)
            return

        if default is None:
            raise KeyError()

        if not isinstance(value, default[0]):
            raise ValueError()

        dict.__setitem__(self, name, value)

    def __enter__(self):
        self._allow_all_writes = True

        return self

    def __exit__(self, exc_type, exc_value, tb):
        self._allow_all_writes = False


class LocalNamespace(dict):
    """Represents the locals namespace in a sandbox.

    This behaves like a dict except with some additional behavior tailored
    to our sandbox execution model.

    Under normal rules of exec(), doing things like += could have interesting
    consequences. Keep in mind that a += is really a read, followed by the
    creation of a new variable, followed by a write. If the read came from the
    global namespace, then the write would go to the local namespace, resulting
    in fragmentation. This is not desired.

    Our local namespaces silently proxies writes to should-be globals to the
    global namespace.

    We also enforce the convention that global variables are UPPERCASE and
    local variables are not. In practice, this means that attempting to
    reference an uppercase variable that isn't defined as a valid global
    variable by the global namespace will result in an exception because the
    global namespace rejects accesses to unknown variables.
    """
    def __init__(self, global_ns):
        self._globals = global_ns
        dict.__init__({})

    def __getitem__(self, name):
        if not isinstance(name, basestring):
            raise TypeError('Only retrieval of string keys is allowed.')

        if name.isupper():
            return self._globals[name]

        return dict.__getitem__(self, name)

    def __setitem__(self, name, value):
        if not isinstance(name, basestring):
            raise TypeError('Only assignment to string keys is allowed.')

        if name.isupper():
            self._globals[name] = value
            return

        dict.__setitem__(self, name, value)


class Sandbox(object):
    """Represents a sandbox for executing a mozbuild config file.

    This class both provides a sandbox for execution of a single mozbuild
    frontend file as well as an interface to the results of that execution.

    Sandbox is effectively a glorified wrapper around compile() + exec(). You
    give it some code to execute and it does that. The main difference from
    executing Python code like normal is that the executed code is very limited
    in what it can do: the sandbox only exposes a very limited set of Python
    functionality. Only specific types and functions are available. This
    prevents executed code from doing things like import modules, open files,
    etc.

    Sandboxes are bound to a MozConfig instance. These objects are produced by
    the output of configure.

    Sandbox instances can be accessed like dictionaries to facilitate result
    retrieval. e.g. foo = sandbox['FOO']. Direct assignment is not allowed.

    Each sandbox has associated with it a GlobalNamespace and LocalNamespace.
    Only data stored in the GlobalNamespace is retrievable via the dict
    interface. This is because the local namespace should be irrelevant. It
    should only contain throwaway variables.
    """
    def __init__(self, config):
        """Initialize an empty sandbox associated with a build configuration.

        The passed in config is the output of configure. All sandboxes have
        access its global data.
        """
        self.config = config

        self._globals = GlobalNamespace()
        self._locals = LocalNamespace(self._globals)

        # Normalize the mozconfig into single dict.
        # TODO make this a method on that type.
        unified = {}
        for k, v in config.defines.iteritems():
            if v == '1':
                unified[k] = True
            elif v == '0':
                unified[k] = False
            else:
                unified[k] = v

        unified.update(config.substs)

        with self._globals as d:
            # Register additional global variables.
            d['TOPSRCDIR'] = config.topsrcdir
            d['TOPOBJDIR'] = config.topobjdir
            d['CONFIG'] = ReadOnlyDefaultDict(unified, global_default=None)

            # Register functions.
            d['include'] = self._include
            d['add_tier_dir'] = self._add_tier_directory

        self._normalized_topsrcdir = os.path.normpath(config.topsrcdir)
        self._tiers = {}
        self._result = None

    def exec_file(self, path):
        """Execute code at a path in the sandbox."""
        source = None

        with open(path, 'r') as fd:
            # compile() needs a newline on Python < 2.7.
            source = fd.read() + '\n'

        self.exec_source(source, path)

    def exec_source(self, source, path):
        """Execute Python code within a string.

        The passed string should contain Python code to be executed. The string
        will be compiled and executed.
        """
        # We don't have to worry about bytecode generation here because we are
        # too low-level for that. However, we could add bytecode generation via
        # the marshall module if parsing performance were ever an issue.

        # TODO intercept exceptions and convert to more helpful types.
        code = compile(source, path, 'exec')
        exec code in self._globals, self._locals

    @property
    def result(self):
        """Obtain the result of the sandbox.

        This is a data structure with the raw results from execution.
        """
        if self._result is not None:
            return self._result

        variables = {}
        for k, v in self._globals.iteritems():
            if k in ('CONFIG', 'TOPSRCDIR', 'TOPOBJDIR'):
                continue

            # Ignore __builtins__ and functions, which should not be uppercase.
            if not k.isupper():
                continue

            variables[k] = v

        # We don't care about locals because that's what they are: locals.
        self._result = {
            'vars': variables,
            'tiers': self._tiers,
        }

        return self._result

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
        # basic precaution and to prevent accidental "escape" from the source
        # tree, we limit access to files in the top source directory.
        normpath = os.path.normpath(os.path.realpath(path))

        if not normpath.startswith(self._normalized_topsrcdir):
            raise Exception('Included files must be under top source '
                'directory');

        self.exec_file(path)

    # Dict interface proxies reads only to global namespace.
    def __len__(self):
        return len(self._globals)

    def __getitem__(self, name):
        return self._globals[name]

    def __iter__(self):
        return iter(self._globals)

    def iterkeys(self):
        return self.__iter__()

    def __contains__(self, key):
        return key in self._globals


class BuildReader(object):
    """Read a tree of mozbuild files into a data structure.

    This is where the build system starts. You give it a tree configuration
    (the output of configuration) and it executes the build.mozbuild files and
    collects the data they define.
    """

    def __init__(self, config):
        self.config = config
        self.topsrcdir = config.topsrcdir

        self._log = logging.getLogger(__name__)
        self._read_files = set()

    def read_topsrcdir(self):
        """Read the tree of mozconfig files into a data structure.

        This starts with the tree's top-most mozbuild file and descends into
        all linked mozbuild files until all relevant files have been evaluated.
        """
        path = os.path.join(self.topsrcdir, 'build.mozbuild')
        self.read_mozbuild(path)

    def read_mozbuild(self, path):
        path = os.path.normpath(path)
        self._log.debug('Reading file: %s' % path)

        if path in self._read_files:
            self._log.warning('File already read. Skipping: %s' % path)
            return

        self._read_files.add(path)

        sandbox = Sandbox(self.config)
        sandbox.exec_file(path)

        result = sandbox.result

        # Traverse into referenced files.

        # We first collect directories populated in variables.
        dir_vars = ['DIRS', 'PARALLEL_DIRS']

        if self.config.defines.get('ENABLE_TESTS', False):
            dir_vars.extend(['TEST_DIRS', 'TEST_TOOL_DIRS'])

        # It's very tempting to use a set here. Unfortunately, the recursive
        # make backend needs order preserved. Once we autogenerate all backend
        # files, we should be able to conver this to a set.
        dirs = []
        for var in dir_vars:
            if not var in result['vars']:
                continue

            for d in result['vars'][var]:
                if d not in dirs:
                    dirs.append(d)

        # We also have tiers whose members are directories.
        for tier, values in result['tiers'].iteritems():
            for var in ('regular', 'static'):
                for d in values[var]:
                    if d not in dirs:
                        dirs.append(d)

        curdir = os.path.dirname(path)
        for relpath in dirs:
            self.read_mozbuild(os.path.join(curdir, relpath, 'build.mozbuild'))
