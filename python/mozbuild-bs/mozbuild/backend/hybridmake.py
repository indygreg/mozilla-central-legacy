# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os.path
import traceback

from pymake.builder import Makefile
from StringIO import StringIO

import mozbuild.frontend.data as data

from mozbuild.backend.base import BackendBase
from mozbuild.backend.utils import makefile_output_path
from mozbuild.backend.utils import substitute_makefile
from mozbuild.util import FileAvoidWrite

IGNORE_PATHS = [
    'security/manager',

    'services/crypto/component',

    'toolkit/identity',
]

def normpath(p):
    """Normalize a path to the format expected by pymake."""
    return p.replace(os.sep, '/')

class HybridMakeBackend(BackendBase):
    """The "hybrid make" backend.

    This backend combines the legacy recursive make files with non-recursive
    make files.

    The generation phase of this backend extracts data from Makefile.in's. For
    pieces it knows how to handle, it writes out an optimized, non-recursive
    .mk file in the output directory. It removes statements from the original
    Makefile.in that are now handled by the dynamically-created non-recursive
    .mk file and writes out the translated Makefile in the output directory,
    just like the legacy backend. It tops things off by writing out a single
    .mk file in the root directory of the object directory that includes all
    the non-recursive .mk files.

    The backend phase invokes both the legacy and non-recursive .mk files in
    the right order so things build properly.
    """
    def __init__(self, *args):
        BackendBase.__init__(self, *args)

        self.splendid_files = set()

        self._makefiles = None

    @property
    def makefiles(self):
        if self._makefiles is None:
            self._makefiles = []

            for makefile in self.frontend.makefiles.makefiles():
                substitute_makefile(makefile, self.frontend)
                self._makefiles.append(makefile)
                yield makefile

            return

        for m in self._makefiles:
            yield m

    ############################
    # Generation Functionality #
    ############################

    def _generate(self):
        for makefile in self.makefiles:
            self._generate_makefile(makefile)

        hybrid_path = os.path.join(self.objdir, 'hybridmake.mk')
        with open(hybrid_path, 'wb') as fh:
            self.print_hybridmake(fh)

        dependencies = [m.filename for m in self.makefiles]
        self.add_generate_output_file(hybrid_path, dependencies)
        self.output_directories.add(os.path.join(self.objdir, 'tmp'))

        for path in self.output_directories:
            self.mkdir(path)

    def _generate_makefile(self, original):
        # TODO MozillaMakefile should use proper statements API.
        output_path = makefile_output_path(self.srcdir, self.objdir, original)
        output_directory = os.path.dirname(output_path)
        original.directory = output_directory

        if not os.path.exists(output_directory):
            os.makedirs(output_directory)

        reldir = original.directory[len(self.objdir) + 1:]

        ignored = False
        for ignore_path in IGNORE_PATHS:
            if reldir.startswith(ignore_path):
                ignored = True
                break

        strip_variables = set()

        if not ignored:
            splendid_path = os.path.join(output_directory, 'splendid.mk')

            try:
                with FileAvoidWrite(splendid_path) as buf:
                    strip_variables = self.write_splendid_makefile(original, buf)

                    if len(buf.getvalue()):
                        self.add_generate_output_file(splendid_path,
                            [original.filename])
                        self.splendid_files.add(splendid_path)
            except:
                self.log(logging.WARNING, 'splendid_generation_error',
                    {'path': original.filename},
                    'Error generating non-recursive makefile for {path}')

                if False:
                    traceback.print_exc()

        makefile = Makefile(output_path)

        for statement in original.statements._statements:
            makefile.append(statement.statement)

        # Strip out variables we handle ourselves so the legacy build system
        # doesn't do anything.
        for name in strip_variables:
            makefile.remove_variable_assignment(name)

        with FileAvoidWrite(output_path) as fh:
            fh.write(makefile.to_source())

        self.add_generate_output_file(output_path, [original.filename])

    def write_splendid_makefile(self, makefile, fh):
        """Writes a splendid, non-recursive make file."""

        strip_variables = set()

        for obj in makefile.get_data_objects():
            method = None
            if isinstance(obj, data.ExportsInfo):
                method = self._write_exports
            elif isinstance(obj, data.XPIDLInfo):
                method = self._write_idl
            elif isinstance(obj, data.LibraryInfo):
                method = self._write_library

            if method:
                strip_variables |= method(makefile, fh, obj)

        return strip_variables

    def _write_exports(self, makefile, fh, obj):
        # Install exported files into proper location. These are
        # typically header files.

        inc_dir = os.path.join(self.objdir, 'dist', 'include')

        directories = sorted(obj.output_directories)
        out_directories = [os.path.join(inc_dir, d) for d in directories]
        self.output_directories |= set(out_directories)
        print >>fh, 'CREATE_DIRS += %s' % ' '.join(
            [normpath(d) for d in out_directories])

        output_filenames = []

        for item in obj.filenames:
            input_filename = item['source']
            output_leaf = item['dest']

            output_directory = os.path.join(inc_dir,
                os.path.dirname(output_leaf))
            output_filename = normpath(os.path.join(inc_dir, output_leaf))
            output_filenames.append(normpath(output_filename))

            print >>fh, '%s: %s' % (normpath(output_filename),
                normpath(input_filename))
            print >>fh, '\t$(INSTALL) -R -m 644 "%s" "%s"\n' % (
                normpath(input_filename), normpath(output_directory))

        print >>fh, 'EXPORT_TARGETS += %s\n' % ' \\\n  '.join(output_filenames)
        print >>fh, 'PHONIES += EXPORT_TARGETS'

        return obj.exclusive_variables

    def _write_idl(self, makefile, fh, obj):
        # IDLs are copied to a common idl directory then they are processed.
        # The copying must complete before processing starts.
        idl_output_directory = os.path.join(self.objdir, 'dist', 'idl')
        header_output_directory = os.path.join(self.objdir, 'dist', 'include')
        components_directory = os.path.join(self.objdir, 'dist', 'bin',
            'components')

        self.output_directories.add(idl_output_directory)
        self.output_directories.add(header_output_directory)
        self.output_directories.add(components_directory)

        gen_directory = os.path.join(makefile.directory, '_xpidlgen')
        deps_directory = os.path.join(makefile.directory, '.deps')
        self.output_directories.add(gen_directory)
        self.output_directories.add(deps_directory)

        output_xpt_files = set()
        xpt_module_basename = '%s.xpt' % obj.module
        xpt_module_path = os.path.join(gen_directory, xpt_module_basename)

        xpt_final_path = os.path.join(components_directory,
            xpt_module_basename)

        for source in sorted(obj.sources):
            basename = os.path.basename(source)
            stripped_name = os.path.splitext(basename)[0]
            header_basename = stripped_name + '.h'
            xpt_basename = stripped_name + '.xpt'

            output_idl_path = os.path.join(idl_output_directory, basename)
            output_header_path = os.path.join(gen_directory, header_basename)
            install_header_path = os.path.join(header_output_directory,
                header_basename)

            xpt_output_path = os.path.join(gen_directory, xpt_basename)
            output_xpt_files.add(normpath(xpt_output_path))

            header_deps_path = os.path.join(deps_directory,
                '%s.pp' % header_basename)

            xpt_deps_path = os.path.join(deps_directory,
                '%s.pp' % xpt_basename)

            # Record the final destination of this IDL in a variable so that
            # variable can be used as a prerequisite.
            print >>fh, 'IDL_DIST_IDL_FILES += %s' % normpath(output_idl_path)
            print >>fh, 'IDL_DIST_H_FILES += %s' % normpath(install_header_path)
            print >>fh, 'IDL_H_FILES += %s' % normpath(output_header_path)
            print >>fh, ''

            # Install the original IDL file into the IDL directory.
            print >>fh, '%s: %s' % (normpath(output_idl_path), normpath(source))
            print >>fh, '\t$(INSTALL) -R -m 664 "%s" "%s"\n' % (
                normpath(source), normpath(idl_output_directory))
            print >>fh, ''

            # Generate the .h header from the IDL file.
            print >>fh, '%s: %s $(IDL_DIST_IDL_FILES)' % (
                normpath(output_header_path), normpath(source))
            print >>fh, '\techo %s; \\' % basename
            print >>fh, '\t$(IDL_GENERATE_HEADER) -d %s -o $@ %s' % (
                normpath(header_deps_path), normpath(source))
            print >>fh, ''

            # Include the dependency file for this header.
            print >>fh, '-include %s' % normpath(header_deps_path)
            print >>fh, ''

            # Install the generated .h header into the dist directory.
            print >>fh, '%s: %s' % (normpath(install_header_path),
                normpath(output_header_path))
            print >>fh, '\t$(INSTALL) -R -m 664 "%s" "%s"\n' % (
                normpath(output_header_path),
                normpath(header_output_directory))
            print >>fh, ''

            # Generate intermediate .xpt file.
            print >>fh, 'IDL_XPT_FILES += %s' % normpath(xpt_output_path)
            print >>fh, '%s: %s' % (normpath(xpt_output_path),
                normpath(output_idl_path))
            print >>fh, '\techo %s; \\' % os.path.basename(xpt_output_path)
            print >>fh, '\t$(IDL_GENERATE_XPT) %s -d %s -o $@' % (
                normpath(output_idl_path), normpath(xpt_deps_path))
            print >>fh, ''

            # Include xpt dependency file.
            print >>fh, '-include %s' % normpath(xpt_deps_path)
            print >>fh, ''

        # Link .xpt files into final .xpt file.
        if obj.link_together:
            print >>fh, 'IDL_XPT_FILES += %s' % normpath(xpt_module_path)
            print >>fh, '%s: %s' % (normpath(xpt_module_path),
                ' '.join(output_xpt_files))
            print >>fh, '\techo %s; \\' % os.path.basename(xpt_module_path)
            print >>fh, '\t$(XPIDL_LINK) %s %s' % (normpath(xpt_module_path),
                ' '.join(output_xpt_files))
            print >>fh, ''

        # Install final .xpt file into dist.
        print >>fh, 'IDL_XPT_INSTALL_FILES += %s' % normpath(xpt_final_path)
        print >>fh, '%s: %s' % (normpath(xpt_final_path),
            normpath(xpt_module_path))
        print >>fh, '\t$(INSTALL) -R -m 664 %s %s' % (
            normpath(xpt_module_path), '$(DIST_COMPONENTS_DIR)')
        print >>fh, ''

        if obj.write_manifest:
            print >>fh, '\t$(IDL_UPDATE_INTERFACES_MANIFEST) "interfaces %s"' % (
                xpt_module_basename)
            print >>fh, '\t$(IDL_UPDATE_CHROME_MANIFEST)'
            print >>fh, ''

        return obj.exclusive_variables

    def _write_library(self, makefile, fh, obj):
        def normalize_path(p):
            if os.path.isabs(p):
                return p

            full = os.path.join(makefile.directory, p)

            return os.path.realpath(full)

        base_args = ['-c']

        for define in obj.defines:
            base_args.append('-D%s' % define)

        for include in obj.includes:
            base_args.append('-I%s' % normalize_path(include))

        base_args.extend(obj.nspr_cflags)

        c_args = list(base_args)
        c_args.extend(obj.c_flags)

        cpp_args = list(base_args)
        cpp_args.extend(obj.cxx_flags)

        deps_dir = os.path.join(makefile.directory, '.deps')
        self.output_directories.add(deps_dir)

        for source in obj.cpp_sources:
            basename = os.path.splitext(os.path.basename(source))[0]
            object_basename = '%s.o' % basename
            deps_basename = '%s.pp' % object_basename

            object_path = os.path.join(makefile.directory, object_basename)
            deps_path = os.path.join(deps_dir, deps_basename)

            # TODO don't hardcode GCC/Clang flags.
            flags = '%s -MD -MF %s' % (obj.compile_cxxflags, deps_path)

            print >>fh, 'CPP_OBJECT_FILES += %s' % normpath(object_path)

            print >>fh, '%s: %s' % (normpath(object_path), normpath(source))
            print >>fh, '\techo %s; \\' % os.path.basename(source)
            print >>fh, '\t$(CCC) -o $@ -c %s %s' % (flags, normpath(source))
            print >>fh, ''

            # Include dependency file.
            print >>fh, '-include %s' % normpath(deps_path)
            print >>fh, ''

        # C files are very similar to C++ files.
        for source in obj.c_sources:
            basename = os.path.splitext(os.path.basename(source))[0]
            object_basename = '%s.o' % basename
            deps_basename = '%s.pp' % object_basename

            object_path = os.path.join(makefile.directory, object_basename)
            deps_path = os.path.join(deps_dir, deps_basename)

            # TODO don't hardcode GCC/Clang flags.
            flags = '%s -MD -MF %s' % (obj.compile_cflags, normpath(deps_path))

            print >>fh, 'C_OBJECT_FILES += %s' % normpath(object_path)

            print >>fh, '%s: %s' % (normpath(object_path), normpath(source))
            print >>fh, '\techo %s; \\' % os.path.basename(source)
            print >>fh, '\t$(CC) -o $@ -c %s %s' % (flags, normpath(source))
            print >>fh, ''

            print >>fh, '-include %s' % normpath(deps_path)
            print >>fh, ''

        # We don't return exclusive_variables because we don't yet have feature
        # parity with rules.mk and stripping these variables causes rules.mk to
        # get confused. We rely on our rules above having the same side-effects
        # as rules.mk. So, by the time rules.mk gets a shot at it, there is
        # nothing to be done and the targets aren't rebuilt.
        return set()

    def print_hybridmake(self, fh):
        print >>fh, '# This file is automatically generated. Do NOT edit.'

        print >>fh, 'TOP_SOURCE_DIR := %s' % normpath(self.srcdir)
        print >>fh, 'OBJECT_DIR := %s' % normpath(self.objdir)

        print >>fh, 'DEPTH := .'
        print >>fh, 'topsrcdir := %s' % normpath(self.srcdir)
        print >>fh, 'srcdir := %s' % normpath(self.srcdir)
        print >>fh, 'include $(topsrcdir)/config/config.mk'

        print >>fh, 'default:'
        print >>fh, '\t@echo "Use mach to build with this file."; \\'
        print >>fh, '\texit 1;'
        print >>fh, '\n'

        for path in sorted(self.splendid_files):
            print >>fh, 'include %s' % normpath(path)

        print >>fh, 'include $(TOP_SOURCE_DIR)/config/makefiles/nonrecursive.mk'

    #######################
    # Build Functionality #
    #######################

    def _build(self):
        for path in self.output_directories:
            self.mkdir(path)

        # We have to run all the tiers separately because the main Makefile's
        # default target removes output directories, which is silly.
        self._run_make(target='export_tier_base')
        self._run_make(filename='hybridmake.mk', target='export')
        self._run_make(target='tier_base')
        self._run_make(target='tier_nspr')
        self._run_make(target='tier_js')
        self._run_make(target='export_tier_platform')

        # We should be able to use the hybridmake libs target immediately.
        # Unfortunately, there are some dependencies on Makefile-specific
        # rules we need to manually do first.

        # DictionaryHelpers.h is installed by a one-off rule.
        self._run_make(directory='js/xpconnect/src', target='libs',
            ignore_errors=True)

        # etld_data.inc is a one-off rule.
        self._run_make(directory='netwerk/dns', target='etld_data.inc')

        # charsetalias.properties.h is installed by a one-off rule.
        self._run_make(directory='intl/locale/src',
            target='charsetalias.properties.h')

        self._run_make(filename='hybridmake.mk', target='libs')
        self._run_make(target='libs_tier_platform')
        self._run_make(target='tools_tier_platform')
        self._run_make(target='export_tier_app')
        self._run_make(target='libs_tier_app')
        self._run_make(target='tools_tier_app')

    def _clean(self):
        pass
