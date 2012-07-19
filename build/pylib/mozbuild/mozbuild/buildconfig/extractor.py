# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains classes used to extract metadata from the Mozilla build
# system.

import hashlib
import logging
import os
import os.path
import sys
import traceback
import xpidl

import mozbuild.buildconfig.data as data

from mozbuild.base import Base
from mozbuild.buildconfig.makefile import Makefile
from mozbuild.buildconfig.makefile import StatementCollection
from mozbuild.buildconfig.mozillamakefile import MozillaMakefile

class MakefileCollection(object):
    """Holds APIs for interacting with multiple Makefiles.

    This is a convenience class so all methods interacting with sets of
    Makefiles reside in one location.
    """
    __slots__ = (
        # Set of paths to all the Makefiles.
        'all_paths',

        'source_directory',
        'object_directory',

        # Dictionary of paths to Makefile instances (cache)
        '_makefiles',
    )

    def __init__(self, source_directory, object_directory):
        assert(os.path.isabs(source_directory))
        assert(os.path.isabs(object_directory))

        self.source_directory = source_directory
        self.object_directory = object_directory

        self.all_paths = set()
        self._makefiles = {}

    def add(self, path):
        """Adds a Makefile at a path to this collection."""
        self.all_paths.add(path)

    def makefiles(self):
        """A generator for Makefile instances from the configured paths.

        Returns instances of Makefile.
        """
        for path in sorted(self.all_paths):
            m = self._makefiles.get(path, None)
            if m is None:
                m = MozillaMakefile(path)
                self._makefiles[path] = m

            yield m

    def includes(self):
        """Obtain information about all the includes in the Makefiles.

        This is a generator of tuples. Eah tuple has the items:

          ( makefile, statement, conditions, path )
        """
        for m in self.makefiles():
            for statement, conditions, path in m.statements.includes():
                yield (m, statement, conditions, path)

    def variable_assignments(self):
        """A generator of variable assignments.

        Each returned item is a tuple of:

          ( makefile, statement, conditions, name, value, type )
        """
        for m in self.makefiles():
            for statement, conditions, name, value, type in m.statements.variable_assignments():
                yield (makefile, statement, conditions, name, value, type)

    def rules(self):
        """A generator for rules in all the Makefiles.

        Each returned item is a tuple of:

          ( makefile, statement, conditions, target, prerequisite, commands )
        """
        for m in self.makefiles():
            for statement, conditions, target, prerequisites, commands in m.statements.rules():
                yield (makefile, statement, conditions, target, prerequisites, commands)

    def static_pattern_rules(self):
        """A generator for static pattern rules in all the Makefiles.

        Each returned item is a tuple of:

          ( makefile, statement, conditions, target, pattern, prerequisite, commands )
        """
        for m in self.makefiles():
            for statement, conditions, target, pattern, prerequisites, commands in m.statements.rules():
                yield (makefile, statement, conditions, target, pattern, prerequisites, commands)

class BuildSystemExtractor(Base):
    """The entity that extracts information from the build system.

    This is the thing that turns Makefile.in's and other signals into data
    structures. If you are looking for the core of the build system, you've
    found it!
    """

    # Constants for identifying build file types
    BUILD_FILE_MAKE_TEMPLATE = 1
    BUILD_FILE_MAKEFILE = 2
    BUILD_FILE_MK = 3
    BUILD_FILE_CONFIGURE_INPUT = 4
    BUILD_FILE_OTHER_IN = 5

    # These relative paths are not managed by us, so we can ignore them
    EXTERNALLY_MANAGED_PATHS = (
        'js/src',
        'nsprpub',
    )

    # Paths in object directory that are produced by configure.
    CONFIGURE_MANAGED_FILES = (
        'config/expandlibs_config.py',
        'config/autoconf.mk',
        'config/doxygen.cfg',
        'gfx/cairo/cairo/src/cairo-features.h',
        'js/src/config/autoconf.mk',
        'js/src/config/expandlibs_config.py',
        'js/src/config.status',
        'js/src/editline/Makefile',   # TODO why is this getting produced?
        'js/src/js-confdefs.h',
        'js/src/js-config',
        'js/src/js-config.h',
        'js/src/Makefile',            # TODO why is this getting produced
        'network/necko-config.h',
        'nsprpub/config/autoconf.mk',
        'nsprpub/config/nspr-config',
        'nsprpub/config/nsprincl.mk',
        'nsprpub/config/nsprincl.sh',
        'nsprpub/config.status',
        'xpcom/xpcom-config.h',
        'xpcom/xpcom-private.h',
        'config.status',
        'mozilla-config.h',
    )

    IGNORE_BUILD_FILES = (
        # Uses order-only prerequisites, which PyMake can't handle.
        # Bug 703843 tracks fixing.
        'build/unix/elfhack/Makefile.in',
    )

    # Files produced by configure that we don't care about
    CONFIGURE_IGNORE_FILES = (
        'js/src/config.log',
        'js/src/unallmakefiles',
        'nsprpub/config.log',
        'config.cache',
        'config.log',
        'unallmakefiles',
    )

    __slots__ = (
        # Holds dictionary of autoconf values for different paths.
        'autoconfs',

        # BuildConfig instance
        'config',

        # Holds state of configure
        'configure_state',

        # Boolean indicating whether we are configured
        '_is_configured',

        # MakefileCollection for the currently loaded Makefiles
        'makefiles',

        # logging.Logger instance
        'logger',
    )

    def __init__(self, config):
        Base.__init__(self, config)

        self.autoconfs = None
        self.configure_state = None
        self._is_configured = None
        self.makefiles = MakefileCollection(config.source_directory,
            config.object_directory)

    @property
    def is_configured(self):
        """Returns whether autoconf has run and the object directory is
        configured."""
        if self._is_configured is None:
            self.refresh_configure_state()

        return self._is_configured is True

    def refresh_configure_state(self):
        """Refreshes state relevant to configure."""
        self.configure_state = {
            'files': {}
        }
        self.autoconfs = {}

        # We clear this flag if it isn't.
        self._is_configured = True

        for path in self.CONFIGURE_MANAGED_FILES:
            full = os.path.join(self.config.object_directory, path)

            # Construct defined variables from autoconf.mk files
            if path[-len('config/autoconf.mk'):] == 'config/autoconf.mk':
                if os.path.exists(full):
                    k = path[0:-len('config/autoconf.mk')].rstrip('/')
                    self.autoconfs[k] = BuildSystemExtractor.convert_autoconf_to_dict(full)
                else:
                    self._is_configured = False

            if not os.path.exists(full) and path in self.configure_state['files']:
                raise Exception('File managed by configure has disappeared. Re-run configure: %s' % path)

            if os.path.exists(full):
                self.configure_state['files'][path] = {
                    'sha1': BuildSystemExtractor.sha1_file_hash(full),
                    'mtime': os.path.getmtime(full),
                }

    def generate_object_directory_makefiles(self):
        """Generates object directory Makefiles from input Makefiles.

        This is a generator that yields tuples of:

          ( relative_directory, filename, MozillaMakefile )

        Presumably, the caller will be writing these Makefiles to disk or will
        be performing analysis of them.
        """
        conversion = self.config.makefile_conversion
        apply_rewrite = conversion == 'rewrite'
        strip_false_conditionals = conversion in ('prune', 'optimized')

        for relative, path in self.source_directory_template_files():
            m = self.generate_object_directory_makefile(
                relative,
                path,
                strip_false_conditionals=strip_false_conditionals,
                apply_rewrite=apply_rewrite,
                verify_rewrite=True
            )

            out_filename = path
            if out_filename[-3:] == '.in':
                out_filename = out_filename[0:-3]

            yield (relative, out_filename, m)

    def generate_object_directory_makefile(self, relative_directory, filename,
                                           strip_false_conditionals=False,
                                           apply_rewrite=False,
                                           verify_rewrite=False):
        """Generates a single object directory Makefile using the given options.

        Returns an instance of MozillaMakefile representing the generated
        Makefile.

        Arguments:

        relative_directory -- Relative directory the input file is located in.
        filename -- Name of file in relative_directory to open.
        strip_false_conditionals -- If True, conditionals evaluated to false
                                    will be stripped from the Makefile. This
                                    implies apply_rewrite=True
        apply_rewrite -- If True, the Makefile will be rewritten from PyMake's
                         parser output. This will lose formatting of the
                         original file. However, the produced file should be
                         functionally equivalent to the original.
        verify_rewrite -- If True, verify the rewritten output is functionally
                          equivalent to the original.
        """
        if strip_false_conditionals:
            apply_rewrite = True

        input_path = os.path.join(self.config.source_directory,
                                  relative_directory, filename)

        def missing_callback(variable):
            self.log(logging.WARNING, 'makefile_substitution_missing',
                     {'path': input_path, 'var': variable},
                     'Missing source variable for substitution: {var} in {path}')

        m = MozillaMakefile(input_path,
                            relative_directory=relative_directory,
                            directory=os.path.join(self.config.object_directory, relative_directory))
        m.perform_substitutions(self, callback_on_missing=missing_callback)

        if strip_false_conditionals:
            m.statements.strip_false_conditionals()
        elif apply_rewrite:
            # This has the side-effect of populating the StatementCollection,
            # which will cause lines to come from it when we eventually write
            # out the content.
            lines = m.statements.lines()

            if verify_rewrite:
                rewritten = StatementCollection(buf='\n'.join(lines),
                                                filename=input_path)

                difference = m.statements.difference(rewritten)
                if difference is not None:
                    self.run_callback(
                        'rewritten_makefile_consistency_failure',
                        {
                            'path': os.path.join(relative_path, filename),
                            'our_expansion': str(difference['our_expansion']),
                            'their_expansion': str(difference['their_expansion']),
                            'why': difference['why'],
                            'ours': str(difference['ours']),
                            'theirs': str(difference['theirs']),
                            'our_line': difference['our_line'],
                            'their_line': difference['their_line'],
                            'index': difference['index']
                        },
                        'Generated Makefile not equivalent: {path} ("{ours}" != "{theirs}")',
                        error=True
                    )
                    raise Exception('Rewritten Makefile not equivalent: %s' % difference)

        return m

    def load_input_build_config_files(self):
        """Loads all files defininig the build configuration.

        This takes whatever configure tells us is relevant to the current build
        configuration and loads it.
        """
        for filename in self.get_input_config_files():
            self.makefiles.add(filename)

    def get_input_config_files(self):
        unallmakefiles = os.path.join(self.objdir, 'unallmakefiles')

        output_files = None

        with open(unallmakefiles, 'rb') as fh:
            output_files = sorted(fh.read().strip().split(' '))

        for output_leaf in output_files:
            yield '%s.in' % output_leaf

        # TODO we also need to pull in GYP files, etc. To do this properly
        # requires co-operation with autoconf. Basically, we need autoconf to
        # write a machine-readable file containing the set of files we are
        # interested in.

    def load_all_object_directory_makefiles(self):
        """Convenience method to load all Makefiles in the object directory.

        This pulls in *all* the Makefiles. You probably want to pull in a
        limited set instead.
        """
        for reldir, name, type in self.object_directory_build_files():
            if type != self.BUILD_FILE_MAKEFILE:
                continue

            path = os.path.join(self.config.object_directory, reldir, name)
            self.makefiles.add(path)

    def source_directory_build_files(self):
        """Obtain all build files in the source directory."""
        it = BuildSystemExtractor.get_build_files_in_tree(
            self.config.source_directory,
            ignore_relative=BuildSystemExtractor.EXTERNALLY_MANAGED_PATHS,
            ignore_full=[self.config.object_directory]
        )
        for t in it:
            if '%s/%s' % ( t[0], t[1] ) not in BuildSystemExtractor.IGNORE_BUILD_FILES:
                yield t

    def source_directory_template_files(self):
        """Obtain all template files in the source directory."""
        for t in self.source_directory_build_files():
            if t[2] == BuildSystemExtractor.BUILD_FILE_MAKE_TEMPLATE:
                outfile = t[1][0:-3]
                if os.path.join(t[0], outfile) in BuildSystemExtractor.CONFIGURE_MANAGED_FILES:
                    continue

                yield (t[0], t[1])

    def object_directory_build_files(self):
        """Obtain all build files in the object directory."""
        it = BuildSystemExtractor.get_build_files_in_tree(self.config.object_directory)
        for t in it: yield t

    def relevant_makefiles(self):
        """Obtains the set of relevant Makefiles for the current build
        configuration.

        This looks at the various DIRs variables and assembles the set of
        consulted Makefiles.
        """
        pass

    def get_tree_info(self):
        """Obtains a TreeInfo instance for the parsed build configuration.

        The returned object represents the currently configured build. It can
        be used to generate files for other build backends.
        """
        tree = data.TreeInfo()
        tree.top_source_directory = self.srcdir
        tree.object_directory = self.objdir

        # TODO This is hacky and should be made more robust.
        autoconf_filename = os.path.join(self.objdir, 'config', 'autoconf.mk')
        variables = BuildSystemExtractor.convert_autoconf_to_dict(autoconf_filename)
        variables['top_srcdir'] = self.srcdir
        variables['configure_input'] = 'Generated by Build Splendid'

        # Extract data from Makefile.in's.
        for makefile in self.makefiles.makefiles():
            # Substitute values from autoconf.mk.
            variables['srcdir'] = os.path.dirname(makefile.filename)

            makefile.perform_substitutions(variables, raise_on_missing=True)

            # Skip over files that cause us pain. For now, this is just things
            # with $(shell), as that can cause weirdness.
            if len(list(makefile.statements.shell_dependent_statements())) > 0:
                continue

            try:
                self._load_makefile_into_tree(tree, makefile)
            except Exception as e:
                print 'Error loading %s' % makefile.filename
                traceback.print_exc()

        # Load data from JAR manifests.
        # TODO look for jar.mn, parse, and load.

        # Parse IDL files loaded into the tree.
        for m, d in tree.xpidl_modules.iteritems():
            for f in d['sources']:
                filename = os.path.normpath(os.path.join(d['source_dir'], f))
                tree.idl_sources[filename] = self._parse_idl_file(filename,
                    tree)

        return tree

    def _load_makefile_into_tree(self, tree, makefile):
        """Loads an individual MozillaMakefile instance into a TreeInfo.

        This is basically a proxy between the MozillaMakefile data extraction
        interface and TreeInfo.
        """
        own_variables = makefile.get_own_variable_names(include_conditionals=True)

        # Prune out lowercase variables, which are defiend as local.
        lowercase_variables = set([v for v in own_variables if v.islower()])

        used_variables = set()

        # Iterate over all the pieces of information extracted from the
        # Makefile, normalize them, and add them to the TreeInfo.
        for obj in makefile.get_data_objects():
            used_variables |= obj.used_variables

            if obj.source_dir is not None:
                tree.source_directories.add(obj.source_dir)

            if isinstance(obj, data.XPIDLInfo):
                module = obj.module
                assert(module is not None)

                tree.xpidl_modules[module] = {
                    'source_dir': obj.source_dir,
                    'module': module,
                    'sources': obj.sources,
                }

                tree.idl_directories.add(obj.source_dir)

            elif isinstance(obj, data.ExportsInfo):
                for k, v in obj.exports.iteritems():
                    k = '/%s' % k

                    if k not in tree.exports:
                        tree.exports[k] = {}

                    for f in v:
                        search_paths = [obj.source_dir]
                        search_paths.extend(obj.vpath)

                        found = False

                        for path in search_paths:
                            filename = os.path.join(path, f)
                            if not os.path.exists(filename):
                                continue

                            found = True
                            tree.exports[k][f] = filename
                            break

                        if not found:
                            raise Exception('Could not find export file: %s from %s' % (
                                f, obj.source_dir))

            elif isinstance(obj, data.LibraryInfo):
                name = obj.name

                if name in tree.libraries:
                    raise Exception('Library aready defined: %s' % name)

                def normalize_include(path):
                    if os.path.isabs(path):
                        return path

                    return os.path.normpath(os.path.join(obj.directory,
                        path))

                includes = []
                for path in obj.includes:
                    includes.append(normalize_include(path))
                for path in obj.local_includes:
                    includes.append(normalize_include(path))

                tree.libraries[name] = {
                    'c_flags': obj.c_flags,
                    'cpp_sources': obj.cpp_sources,
                    'cxx_flags': obj.cxx_flags,
                    'defines': obj.defines,
                    'includes': includes,
                    'pic': obj.pic,
                    'is_static': obj.is_static,
                    'source_dir': obj.source_dir,
                    'output_dir': obj.directory,
                }

            elif isinstance(obj, data.MiscInfo):
                if obj.included_files is not None:
                    for path in obj.included_files:
                        pass
                        #v = self.included_files.get(path, set())
                        #v.add(makefile.filename)
                        #self.included_files[path] = v

        # Set math \o/
        unused_variables = own_variables - used_variables - lowercase_variables
        for var in unused_variables:
            # TODO report unhandled variables in tree
            pass

    def _parse_idl_file(self, filename, tree):
        idl_data = open(filename, 'rb').read()
        p = xpidl.IDLParser()
        idl = p.parse(idl_data, filename=filename)

        # TODO It probably isn't correct to search *all* IDL directories
        # because the same file may be defined multiple places.
        idl.resolve(tree.idl_directories, p)

        return {
            'filename': filename,
            'dependencies': [os.path.normpath(dep) for dep in idl.deps],
        }

    def autoconf_for_path(self, path):
        """Obtains a dictionary of variable values from the autoconf file
        relevant for the specified path.
        """
        assert(self.is_configured)
        for managed in BuildSystemExtractor.EXTERNALLY_MANAGED_PATHS:
            if path.find(managed) == 0:
                return self.autoconfs[managed]

        return self.autoconfs['']

    def log(self, level, action, params, format_str):
        self.logger.log(level, format_str,
                        extra={'action': action, 'params': params})

    @staticmethod
    def convert_autoconf_to_dict(path):
        """Convert the autoconf file at the specified path to a dictionary
        of name-value pairs.

        This assumes that our autoconf files don't have complex logic. It will
        raise if they do.
        """
        d = {}

        allowed_types = (
            StatementCollection.VARIABLE_ASSIGNMENT_SIMPLE,
            StatementCollection.VARIABLE_ASSIGNMENT_RECURSIVE
        )

        statements = StatementCollection(filename=path)

        # We evaluate ifeq's because the config files /should/ be
        # static. We don't rewrite these, so there is little risk.
        statements.strip_false_conditionals(evaluate_ifeq=True)

        for statement, conditions, name, value, type in statements.variable_assignments():
            if len(conditions):
                raise Exception(
                    'Conditional variable assignment encountered (%s) in autoconf file: %s' % (
                        name, statement.location ))

            if name in d:
                if type not in allowed_types:
                    raise Exception('Variable assigned multiple times in autoconf file: %s' % name)

            d[name] = value

        return d

    @staticmethod
    def get_build_files_in_tree(path, ignore_relative=None, ignore_full=None):
        """Find all build files in the directory tree under the given path.

        This is a generator of tuples. Each tuple is of the form:

          ( reldir, filename, type )

        Where reldir is the relative directory from the path argument,
        filename is the str of the build filename, and type is a
        BuildSystemExtractor.BUILD_FILE_* constant.

        Arguments:

          path - Path to directory to recurse.
          ignore_relative - Iterable of relative directory names to ignore.
          ignore_full - Iterable of full paths to ignore.
        """
        assert(os.path.isabs(path))

        if ignore_relative is None:
            ignore_relative = []

        if ignore_full is None:
            ignore_full = []

        for root, dirs, files in os.walk(path):
            relative = root[len(path)+1:]

            # Filter out ignored directories
            ignored = False
            for ignore in ignore_relative:
                if relative.find(ignore) == 0:
                    ignored = True
                    break

            if ignored:
                continue

            for ignore in ignore_full:
                if root.find(ignore) == 0:
                    ignored = True
                    break

            if ignored:
                continue

            for name in files:
                if name == 'configure.in':
                    yield (relative, name, BuildSystemExtractor.BUILD_FILE_CONFIGURE_INPUT)
                elif name[-6:] == '.mk.in' or name == 'Makefile.in':
                    yield (relative, name, BuildSystemExtractor.BUILD_FILE_MAKE_TEMPLATE)
                elif name[-3:] == '.in':
                    yield (relative, name, BuildSystemExtractor.BUILD_FILE_OTHER_IN)
                elif name == 'Makefile':
                    yield (relative, name, BuildSystemExtractor.BUILD_FILE_MAKEFILE)
                elif name[-3:] == '.mk':
                    yield (relative, name, BuildSystemExtractor.BUILD_FILE_MK)

    @staticmethod
    def sha1_file_hash(filename):
        h = hashlib.sha1()
        with open(filename, 'rb') as fh:
            while True:
                data = fh.read(8192)
                if not data:
                    break

                h.update(data)

        return h.hexdigest()
