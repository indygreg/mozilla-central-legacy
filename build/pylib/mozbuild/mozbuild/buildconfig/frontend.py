# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains code for managing the "frontend" files of the Mozilla
# build system.

import os

import mozbuild.buildconfig.data as data

from mozbuild.base import Base
from mozbuild.buildconfig.makefile import MakefileCollection
from mozbuild.buildconfig.mozillamakefile import MozillaMakefile

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

CONFIGURE_IGNORE_FILES = (
    'js/src/config.log',
    'js/src/unallmakefiles',
    'nsprpub/config.log',
    'config.cache',
    'config.log',
    'unallmakefiles',
)

class BuildFrontend(Base):
    """Provides an interface to the build config files in a source tree.

    This is used to load the input files which will be used to generate files
    for a build backend.
    """

    def __init__(self, config):
        Base.__init__(self, config)

        self.makefiles = MakefileCollection(self.srcdir, self.objdir)

    @property
    def autoconf_output_files(self):
        """The output files managed by autoconf.

        This is basically a parser for unallmakefiles from the object
        directory.

        It is a generator of str which correlate to the relative paths of
        output files in the object directory.
        """
        unallmakefiles = os.path.join(self.objdir, 'unallmakefiles')

        output_files = None

        with open(unallmakefiles, 'rb') as fh:
            output_files = sorted(fh.read().strip().split(' '))

        return output_files

    @property
    def autoconf_input_files(self):
        """The input files as reported by autoconf.

        This converts the output of autoconf_output_files into the source
        filenames.
        """
        return ['%s.in' % p for p in self.autoconf_output_files]

    @property
    def all_input_files(self):
        """The comprehensive set of input files.

        This crawls the filesystem and finds every input file.
        """
        it = BuildFrontend.get_build_files_in_tree(
            self.srcdir,
            ignore_relative=EXTERNALLY_MANAGED_PATHS,
            ignore_full=[self.objdir])

        for (relative, name, cat) in it:
            if cat == BUILD_FILE_MAKE_TEMPLATE:
                if name == 'Makefile.in':
                    yield os.path.join(relative, name)

    def load_autoconf_input_files(self):
        """Loads all autoconf reported config files into this instance.

        This loads the subset of config files that autoconf says is active. It
        may be incomplete.
        """
        for relative in self.autoconf_input_files:
            self.load_input_file(relative)

    def load_all_input_files(self):
        for relative in self.all_input_files:
            self.load_input_file(relative)

    def load_input_file(self, relative):
        """Load an input from the source directory at the specified path."""

        if not relative.endswith('Makefile.in'):
            return

        if relative in IGNORE_BUILD_FILES:
            return

        m = MozillaMakefile(os.path.join(self.srcdir, relative))
        self.makefiles.add(m)

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
    def get_frontend_files(path, ignore_relative=None, ignore_full=None):
        """Find all build files in the directory tree under the given path.

        This is a generator of tuples. Each tuple is of the form:

          ( reldir, filename, type )

        Where reldir is the relative directory from the path argument,
        filename is the str of the build filename, and type is a
        BUILD_FILE_* constant.

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
                    yield (relative, name, BUILD_FILE_CONFIGURE_INPUT)
                elif name[-6:] == '.mk.in' or name == 'Makefile.in':
                    yield (relative, name, BUILD_FILE_MAKE_TEMPLATE)
                elif name[-3:] == '.in':
                    yield (relative, name, BUILD_FILE_OTHER_IN)
                elif name == 'Makefile':
                    yield (relative, name, BUILD_FILE_MAKEFILE)
                elif name[-3:] == '.mk':
                    yield (relative, name, BUILD_FILE_MK)
