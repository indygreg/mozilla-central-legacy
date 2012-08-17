# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains code for extracting metadata from a Mozilla Makefile.

import os.path

import mozbuild.frontend.data as data

from mozbuild.frontend.makefile import Makefile

class MozillaMakefile(Makefile):
    """A Makefile with knowledge of Mozilla's build system.

    This is the class used to extract metadata from the Makefiles.
    """

    """Traits that can identify a Makefile"""
    MODULE       = 1
    LIBRARY      = 2
    DIRS         = 3
    XPIDL        = 4
    EXPORTS      = 5
    TEST         = 6
    PROGRAM      = 7

    """Variables common in most Makefiles that aren't really that special.

    This list is used to help identify variables we don't do anything with."""
    COMMON_VARIABLES = [
        'DEPTH',            # Defined at top of file
        'topsrcdir',        # Defined at top of file
        'srcdir',           # Defined at top of file
        'VPATH',            # Defined at top of file
        'relativesrcdir',   # Defined at top of file. # TODO is this used by anything?
        'DIRS',             # Path traversal
        'PARALLEL_DIRS',    # Path traversal
        'TOOL_DIRS',        # Path traversal
    ]

    """This list tracks all variables that are still in the wild but aren't used"""
    UNUSED_VARIABLES = []

    __slots__ = (
        # Path within tree this Makefile is present at
        'relative_directory',

        # Set of traits exhibited by this file
        'traits',
    )

    def __init__(self, filename, relative_directory=None, directory=None):
        """Interface for Makefiles with Mozilla build system knowledge."""
        Makefile.__init__(self, filename, directory=directory)

        self.relative_directory = relative_directory
        self.traits = None

    def __getstate__(self):
        state = Makefile.__getstate__(self)
        state['relative_directory'] = self.relative_directory

        return state

    def __setstate__(self, state):
        Makefile.__setstate__(self, state)

        self.relative_directory = state['relative_directory']
        self.traits = None

    #def perform_substitutions(self, bse, callback_on_missing=None):
    #    """Perform substitutions on this Makefile.
    #
    #    This overrides the parent method to apply Mozilla-specific
    #    functionality.
    #    """
    #    assert(isinstance(bse, BuildSystemExtractor))
    #    assert(self.relative_directory is not None)
    #
    #    autoconf = bse.autoconf_for_path(self.relative_directory)
    #    mapping = autoconf.copy()
    #
    #    mapping['configure_input'] = 'Generated automatically from Build Splendid'
    #    mapping['top_srcdir'] = bse.config.source_directory
    #    mapping['srcdir'] = os.path.join(bse.config.source_directory,
    #                                     self.relative_directory)
    #
    #    Makefile.perform_substitutions(self, mapping,
    #                                            callback_on_missing=callback_on_missing)

    def get_traits(self):
        """Obtain traits of the Makefile.

        Traits are recognized patterns that invoke special functionality in
        Mozilla's Makefiles. Traits are identified by the presence of specific
        named variables."""
        if self.traits is not None:
            return self.traits

        self.traits = set()
        variable_names = self.get_own_variable_names(include_conditionals=True)
        for name in variable_names:
            if name == 'MODULE':
                self.traits.add(self.MODULE)
            elif name == 'LIBRARY_NAME':
                self.traits.add(self.LIBRARY)
            elif name == 'DIRS' or name == 'PARALLEL_DIRS':
                self.traits.add(self.DIRS)
            elif name in ('XPIDL_MODULE', 'XPIDLSRCS', 'SDK_XPIDLSRCS'):
                self.traits.add(self.XPIDL)
            elif name in ('EXPORTS', 'EXPORTS_NAMESPACES'):
                self.traits.add(self.EXPORTS)
            elif name in ('_TEST_FILES', 'XPCSHELL_TESTS', '_BROWSER_TEST_FILES', '_CHROME_TEST_FILES'):
                self.traits.add(self.TEST)
            elif name in ('PROGRAM'):
                self.traits.add(self.PROGRAM)

        return self.traits

    def get_dirs(self):
        dirs = self.get_variable_split('DIRS')
        dirs.extend(self.get_variable_split('PARALLEL_DIRS'))

        return dirs

    def is_module(self):
        return self.MODULE in self.get_traits()

    def is_xpidl_module(self):
        return self.XPIDL_MODULE in self.get_traits()

    def get_module(self):
        return self.get_variable_string('MODULE')

    def get_reldir(self):
        absdir = os.path.abspath(self.dir)

        return absdir[len(self.get_objtop())+1:]

    def get_objtop(self):
        depth = self.get_variable_string('DEPTH')
        if not depth:
            depth = self.get_variable_string('MOD_DEPTH')

        return os.path.abspath(os.path.join(self.dir, depth))

    def get_top_source_dir(self):
        return self.get_variable_string('topsrcdir')

    def get_source_dir(self):
        return self.get_variable_string('srcdir')

    def get_transformed_reldir(self):
        return self.get_reldir().replace('\\', '_').replace('/', '_')

    def resolve_absolute_path(self, path, obj):
        assert isinstance(obj, data.MakefileDerivedObject)

        if os.path.isabs(path):
            return path

        search_dirs = [obj.directory, obj.source_dir]
        search_dirs.extend(obj.vpath)

        for search_dir in search_dirs:
            try_path = os.path.join(search_dir, path)

            if os.path.exists(try_path):
                return try_path

        raise Exception('Could not find source file: %s' % path)

    def normalize_compiler_arguments(self, arguments, directory):
        """Normalizes compiler arguments to sane values."""

        rewritten = []

        for value in arguments:
            value = value.strip()

            # Normalize includes to absolute paths. The Makefile's often deal
            # with relative paths. If we fail to do this, we have two problems.
            # First, we would need to cd into the Makefile's directory for
            # compilation. We could do that. The more important problem is that
            # when specifying relative paths, the dependency output file will
            # use relative paths. Since the dependency files may get included
            # from any directory, this is no good. We need absolute paths
            # everywhere.
            # TODO handle non-GCC like compilers.
            if value.startswith('-I'):
                path = value[2:]

                if not os.path.isabs(path):
                    path = os.path.join(directory, path)

                normalized = os.path.normpath(path)

                rewritten.append(value[0:2] + normalized)
                continue

            rewritten.append(value)

        return rewritten

    def get_compiler_flags(self, l, source_var, varnames):
        var_values = {}
        for name in varnames:
            value = self.get_variable_split(name)

            if not len(value):
                continue

            var_values[name] = value

        # Here there be dragons.
        #
        # Makefiles have target-specific variables. These are variables that
        # only apply when evaluated in the context of a specific target. And,
        # our build system uses them to control compiler flags. In the ideal
        # world, our build system wouldn't do this and would accomplish
        # file-specific flags through some other, easier-to-parse means. But,
        # it does, and we have to deal with it.
        #
        # Because evaluating the variables for each target separately is
        # expensive (you evaluate once per target rather than just a few times
        # per make file), we go with an alternate approach. We look at all the
        # target-specific variable assignments (they aren't too many of them).
        # Only if the target and variable is relevant do we pull it in. And, as
        # a bonus, we don't need to evaluate variables in the context of
        # targets!
        target_flags = {}

        sources = getattr(l, source_var)

        targets = {}
        obj_suffix = self.get_variable_string('OBJ_SUFFIX')

        for p in sources:
            basename = os.path.basename(p)
            targets['%s.%s' % (os.path.splitext(basename)[0], obj_suffix)] = p

        evaluate_targets = {}

        for tup in self.statements.target_specific_variable_assignments():
            target = tup[0].statement.targetexp.resolvestr(self.makefile,
                self.makefile.variables)

            if not target in targets:
                continue

            if not tup[2] in varnames:
                continue

            t = evaluate_targets.get(target, set())
            t.add(tup[2])
            evaluate_targets[target] = t

        target_flags = {}

        for target, target_vars in evaluate_targets.iteritems():
            values = {}

            make_target = self.makefile.gettarget(target)

            for target_var in target_vars:
                value = make_target.variables.get(target_var, True)[2]
                values[target_var] = value.resolvesplit(self.makefile,
                    make_target.variables)

            target_flags[targets[target]] = values

        # We need to merge the target flags with the global ones if the target
        # does not provide that variable.
        for path, variables in target_flags.iteritems():
            for k, v in var_values.iteritems():
                if k not in variables:
                    variables[k] = v

        # Finally collapse down into a single list.
        for path in target_flags.keys():
            arguments = []
            for flags in target_flags[path].values():
                arguments.extend(flags)
            target_flags[path] = self.normalize_compiler_arguments(
                arguments, l.directory)

        arguments = []
        for flags in var_values.values():
            arguments.extend(self.normalize_compiler_arguments(flags,
                l.directory))

        return arguments, target_flags

    def get_library_info(self):
        """Obtain information for the library defined by this Makefile.

        Returns a data.LibraryInfo instance"""
        l = data.LibraryInfo(self)

        # It is possible for the name to be not defined if the trait was
        # in a conditional that wasn't true.
        l.used_variables.add('LIBRARY_NAME')
        name = self.get_variable_string('LIBRARY_NAME')
        l.name = name

        # TODO We used to care about all the individual variables before. We no
        # longer do. The following can arguably be deleted since we just grab
        # all of the flags below.
        l.used_variables.add('DEFINES')
        for define in self.get_variable_split('DEFINES'):
            if define[0:2] == '-D':
                l.defines.add(define[2:])
            else:
                l.defines.add(define)

        l.used_variables.add('HOST_CFLAGS')
        for f in self.get_variable_split('HOST_CFLAGS'):
            l.c_flags.add(f)

        l.used_variables.add('HOST_CXXFLAGS')
        for f in self.get_variable_split('HOST_CXXFLAGS'):
            l.cxx_flags.add(f)

        l.used_variables.add('NSPR_CFLAGS')
        for f in self.get_variable_split('NSPR_CFLAGS'):
            l.nspr_cflags.add(f)

        l.used_variables.add('CPPSRCS')
        l.exclusive_variables.add('CPPSRCS')
        for f in self.get_variable_split('CPPSRCS'):
            l.cpp_sources.add(self.resolve_absolute_path(f, l))

        l.used_variables.add('CSRCS')
        l.exclusive_variables.add('CSRCS')
        for f in self.get_variable_split('CSRCS'):
            l.c_sources.add(self.resolve_absolute_path(f, l))

        l.used_variables.add('CMSRCS')
        l.exclusive_variables.add('CMSRCS')
        for f in self.get_variable_split('CMSRCS'):
            l.objc_sources.add(self.resolve_absolute_path(f, l))

        l.used_variables.add('CMMSRCS')
        l.exclusive_variables.add('CMMSRCS')
        for f in self.get_variable_split('CMMSRCS'):
            l.objcpp_sources.add(self.resolve_absolute_path(f, l))

        # LIBXUL_LIBRARY implies static library generation and presence in
        # libxul.
        l.used_variables.add('LIBXUL_LIBRARY')
        if self.has_own_variable('LIBXUL_LIBRARY'):
            l.is_static = True

        # FORCE_STATIC_LIB forces generation of a static library
        l.used_variables.add('FORCE_STATIC_LIB')
        if self.has_own_variable('FORCE_STATIC_LIB'):
            l.is_static = True

        l.used_variables.add('FORCE_SHARED_LIB')
        if self.has_own_variable('FORCE_SHARED_LIB'):
            l.is_shared = True

        l.used_variables.add('USE_STATIC_LIBS')
        if self.has_own_variable('USE_STATIC_LIBS'):
            l.use_static_libs = True

        # IS_COMPONENT is used for verification. It also has side effects for
        # linking flags.
        l.used_variables.add('IS_COMPONENT')
        if self.has_own_variable('IS_COMPONENT'):
            l.is_component = self.get_variable_string('IS_COMPONENT') == '1'

        l.used_variables.add('EXPORT_LIBRARY')
        if self.has_own_variable('EXPORT_LIBRARY'):
            l.export_library = self.get_variable_string('EXPORT_LIBRARY') == '1'

        l.used_variables.add('INCLUDES')
        for s in self.get_variable_split('INCLUDES'):
            if s[0:2] == '-I':
                l.includes.add(s[2:])
            else:
                l.includes.add(s)

        l.used_variables.add('LOCAL_INCLUDES')
        for s in self.get_variable_split('LOCAL_INCLUDES'):
            if s[0:2] == '-I':
                l.local_includes.add(s[2:])
            else:
                l.local_includes.add(s)

        # SHORT_LIBNAME doesn't appears to be used, but we preserve it anyway.
        l.used_variables.add('SHORT_LIBNAME')
        if self.has_own_variable('SHORT_LIBNAME'):
            l.short_libname = self.get_variable_string('SHORT_LIBNAME')

        l.used_variables.add('SHARED_LIBRARY_LIBS')
        for lib in self.get_variable_split('SHARED_LIBRARY_LIBS'):
            l.shared_library_libs.add(lib)

        # This is the new way of obtaining the flags. It emulates
        # COMPILE_CXXFLAGS. We could probably use pymake.data.Expansion
        # directly...
        flags_vars = ['STL_FLAGS', 'VISIBILITY_FLAGS', 'DEFINES', 'INCLUDES',
            'DSO_CFLAGS', 'DSO_PIC_CFLAGS', 'CXXFLAGS', 'RTL_FLAGS',
            'OS_CPPFLAGS']

        cxx_arguments, target_flags = self.get_compiler_flags(l, 'cpp_sources',
            flags_vars)
        l.source_specific_flags.update(target_flags)

        extra_arguments = [
            '-include',
            '$(OBJECT_DIR)/mozilla-config.h',
            '-DMOZILLA_CLIENT',
        ]

        cxx_arguments.extend(extra_arguments)

        l.compile_cxxflags = ' '.join(cxx_arguments)

        # Objective-C++ uses almost the same mechanism.
        cmm_arguments, target_flags = self.get_compiler_flags(l,
            'objcpp_sources', ['COMPILE_CMMFLAGS'])
        l.source_specific_flags.update(target_flags)
        l.objcpp_compile_flags = l.compile_cxxflags + ' ' + ' '.join(cmm_arguments)

        flags_vars = ['VISIBILITY_FLAGS', 'DEFINES', 'INCLUDES', 'DSO_CFLAGS',
            'DSO_PIC_CFLAGS', 'CFLAGS', 'RTL_FLAGS', 'OS_CFLAGS']

        c_arguments, target_flags = self.get_compiler_flags(l, 'c_sources',
            flags_vars)
        l.source_specific_flags.update(target_flags)
        c_arguments.extend(extra_arguments)

        l.compile_cflags = ' '.join(c_arguments)

        cm_arguments, target_flags = self.get_compiler_flags(l, 'objc_sources',
            ['COMPILE_CMFLAGS'])
        l.source_specific_flags.update(target_flags)
        l.objc_compile_flags = l.compile_cflags + ' ' + ' '.join(cm_arguments)

        # Normalize to strings.
        for k, v in l.source_specific_flags.iteritems():
            v.extend(extra_arguments)
            l.source_specific_flags[k] = ' '.join(v)

        # TODO the above seems like a DRY violation.

        return l

    def get_data_objects(self):
        """Retrieve data objects derived from the Makefile.

        This is the main function that extracts metadata from individual
        Makefiles and turns them into Python data structures.

        This method emits a set of MakefileDerivedObjects which describe the
        Makefile. These objects each describe an individual part of the
        build system, e.g. libraries, IDL files, tests, etc. These emitted
        objects can be fed into another system for conversion to another
        build system, fed into a monolithic data structure, etc.
        """
        misc = data.MiscInfo(self)
        tracker = data.UsedVariableInfo(self)
        for v in self.COMMON_VARIABLES:
            tracker.used_variables.add(v)

        for v in self.UNUSED_VARIABLES:
            tracker.used_variables.add(v)

        traits = self.get_traits()

        if self.MODULE in traits:
            tracker.used_variables.add('MODULE')
            # TODO emit MakefileDerivedObject instance
            #tree.register_module(self.get_module(), self.dir)

        if self.LIBRARY in traits:
            li = self.get_library_info()
            yield li

        if self.PROGRAM in traits:
            # TODO capture programs. Executables and libraries are two sides of
            # the same coin. How should this be captured?
            pass

        # MODULE_NAME is only used for error checking, it appears.
        tracker.used_variables.add('MODULE_NAME')

        # EXPORTS and friends holds information on what files to copy
        # to an output directory.
        if self.EXPORTS in traits:
            exports = data.ExportsInfo(self)

            def handle_export(namespace, filename):
                filename = self.resolve_absolute_path(filename, exports)
                exports.output_directories.add(namespace)
                output_leaf = os.path.join(namespace,
                    os.path.basename(filename))

                exports.filenames.append({
                    'source': filename,
                    'dest': output_leaf,
                })

            exports.used_variables.add('EXPORTS')
            exports.exclusive_variables.add('EXPORTS')
            for export in sorted(set(self.get_variable_split('EXPORTS'))):
                handle_export('', export)

            exports.used_variables.add('EXPORTS_NAMESPACES')
            exports.exclusive_variables.add('EXPORTS_NAMESPACES')
            for namespace in self.get_variable_split('EXPORTS_NAMESPACES'):
                varname = 'EXPORTS_%s' % namespace
                exports.used_variables.add(varname)
                exports.exclusive_variables.add(varname)

                # We feed into a set because there are some duplicates.
                # TODO fix these in the tree and treat as fatal errors.
                for s in sorted(set(self.get_variable_split(varname))):
                    handle_export(namespace, s)

            yield exports

        # XP IDL file generation
        if self.XPIDL in traits:
            idl = data.XPIDLInfo(self)
            idl.used_variables.add('XPIDL_MODULE')
            idl.used_variables.add('MODULE')
            if self.has_own_variable('XPIDL_MODULE'):
                idl.module = self.get_variable_string('XPIDL_MODULE')
            elif self.has_own_variable('MODULE'):
                idl.module = self.get_variable_string('MODULE')
            else:
                raise Exception('XPIDL trait without XPIDL_MODULE or MODULE defined')

            idl.used_variables.add('NO_INTERFACES_MANIFEST')
            if self.has_own_variable('NO_INTERFACES_MANIFEST'):
                idl.write_manifest = False

            def add_idl(leaf):
                assert not os.path.isabs(leaf)

                path = os.path.join(idl.source_dir, leaf)
                assert os.path.exists(path)

                idl.sources.add(path)

            idl.used_variables.add('XPIDLSRCS')
            if self.has_own_variable('XPIDLSRCS'):
                idl.exclusive_variables.add('XPIDLSRCS')
                for f in self.get_variable_split('XPIDLSRCS'):
                    add_idl(f)

            # rules.mk merges SDK_XPIDLSRCS together, so we treat as the same
            if self.has_own_variable('SDK_XPIDLSRCS'):
                idl.exclusive_variables.add('SDK_XPIDLSRCS')
                for f in self.get_variable_split('SDK_XPIDLSRCS'):
                    add_idl(f)

            # No need to perform final link if the XPT is already generated by
            # a source of the same name.
            if len(idl.sources) < 2 and idl.module in idl.sources:
                idl.link_together = False

            # Some files give off the scent but don't actually define any IDLs.
            # Here, we prevent empty output.
            if len(idl.sources):
                yield idl

        # Test definitions
        if self.TEST in traits:
            ti = data.TestInfo(self)

            # Regular test files
            ti.used_variables.add('_TEST_FILES')
            if self.has_own_variable('_TEST_FILES'):
                for f in self.get_variable_split('_TEST_FILES'):
                    ti.test_files.add(f)

            # Identifies directories holding xpcshell test files
            ti.used_variables.add('XPCSHELL_TESTS')
            if self.has_own_variable('XPCSHELL_TESTS'):
                for dir in self.get_variable_split('XPCSHELL_TESTS'):
                    ti.xpcshell_test_dirs.add(dir)

            # Files for browser tests
            ti.used_variables.add('_BROWSER_TEST_FILES')
            if self.has_own_variable('_BROWSER_TEST_FILES'):
                for f in self.get_variable_split('_BROWSER_TEST_FILES'):
                    ti.browser_test_files.add(f)

            # Files for chrome tests
            ti.used_variables.add('_CHROME_TEST_FILES')
            if self.has_own_variable('_CHROME_TEST_FILES'):
                for f in self.get_variable_split('_CHROME_TEST_FILES'):
                    ti.chrome_test_files.add(f)

            yield ti

        misc.used_variables.add('GRE_MODULE')
        if self.has_own_variable('GRE_MODULE'):
            misc.is_gre_module = True

        #misc.used_variables.add('PLATFORM_DIR')
        #for d in self.get_variable_split('PLATFORM_DIR'):
        #    misc.platform_dirs.add(d)

        #misc.used_variables.add('CHROME_DEPS')
        #for d in self.get_variable_split('CHROME_DEPS'):
        #    misc.chrome_dependencies.add(d)

        # DEFINES is used by JarMaker too. Unfortunately, we can't detect
        # when to do JarMaker from Makefiles (bug 487182 might fix it), so
        # we just pass it along.
        misc.used_variables.add('DEFINES')
        if self.has_own_variable('DEFINES'):
            for define in self.get_variable_split('DEFINES'):
                if define[0:2] == '-D':
                    misc.defines.add(define[2:])
                else:
                    misc.defines.add(define)

        # TODO add an info object for JavaScript-related
        misc.used_variables.add('EXTRA_JS_MODULES')
        if self.has_own_variable('EXTRA_JS_MODULES'):
            for js in self.get_variable_split('EXTRA_JS_MODULES'):
                misc.extra_js_module.add(js)

        misc.used_variables.add('EXTRA_COMPONENTS')
        if self.has_own_variable('EXTRA_COMPONENTS'):
            for c in self.get_variable_split('EXTRA_COMPONENTS'):
                misc.extra_components.add(c)

        misc.used_variables.add('GARBAGE')
        if self.has_own_variable('GARBAGE'):
            for g in self.get_variable_split('GARBAGE'):
                misc.garbage.add(g)

        misc.included_files = [t[0] for t in self.statements.includes()]

        yield tracker
        yield misc
