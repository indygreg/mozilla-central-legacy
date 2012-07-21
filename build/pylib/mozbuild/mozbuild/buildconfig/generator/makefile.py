# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains code for turning the Python build system data structures
# into Makefiles.

import os
import traceback

from pymake.builder import Makefile

import mozbuild.buildconfig.data as data

from mozbuild.buildconfig.generator.base import Generator

class MakefileGenerator(Generator):
    """Generator that produces Makefiles.

    This is mostly tailored to the existing, legacy build system.
    """
    def __init__(self, frontend):
        Generator.__init__(self, frontend)

        self.reformat = False
        self.strip_false_conditionals = False
        self.verify_reformat = False

    def generate(self):
        for makefile in self.makefiles():
            self._write_makefile(makefile)

    def clean(self):
        for makefile in self.frontend.makefiles.makefiles():
            path = self.output_path_from_makefile(makefile)

            if not os.path.exists(path):
                continue

            print 'Removing output file: %s' % path
            os.unlink(path)

    def makefiles(self):
        """Generator for converted Makefile instances."""
        for makefile in self.frontend.makefiles.makefiles():
            self._generate_makefile(makefile)
            yield makefile

    def output_path_from_makefile(self, makefile):
        basename = os.path.basename(makefile.filename)
        input_directory = makefile.directory
        leaf = input_directory[len(self.srcdir) + 1:]

        return os.path.join(self.objdir, leaf, basename).rstrip('.in')

    def _generate_makefile(self, makefile):
        assert makefile.filename.endswith('.in')

        output_path = self.output_path_from_makefile(makefile)

        variables = dict(self.frontend.autoconf)
        variables['top_srcdir'] = self.srcdir
        variables['srcdir'] = makefile.directory

        # The first step is variable subsitution.
        makefile.perform_substitutions(variables, raise_on_missing=True)

    def _write_makefile(self, makefile):
        output_path = self.output_path_from_makefile(makefile)

        print 'Writing %s' % output_path

        output_dir = os.path.dirname(output_path)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, 0777)

        with open(output_path, 'w') as fh:
            # This is hacky and is needed until makefile.py uses pymake's API.
            if self.reformat:
                from pymake.parser import parsestring

                source = '\n'.join(makefile.lines())
                statements = parsestring(source, output_path)
                print >>fh, statements.to_source()

                # TODO verify rewrite.
            else:
                for line in makefile.lines():
                    print >>fh, line

class HybridMakefileGenerator(Generator):
    """The writes some optimized make files alongside legacy make files.

    This generator looks at extracted data from the original Makefile.in's. For
    the pieces it knows how to handle, it writes out an optimized,
    non-recursive make file (splendid.mk) in the output directory containing
    all the rules it knows how to handle. It writes out a single make file in
    the top-level directory which simply includes all the splendid.mk files.

    It removes references to data from the input Makefile.in and writes out the
    Makefile with the remaining content to the object directory.
    """

    def __init__(self, frontend):
        Generator.__init__(self, frontend)

        # Avoid fragile base class problem.
        self.vanilla = MakefileGenerator(frontend)
        self.splendid_files = set()

        # Make sucks at managing output directories. So, during generation, we
        # collect the set of output directories we know we need to create and
        # we create them, like a boss.
        self.output_directories = set()

    def generate(self):
        #self.tree = self.frontend.get_tree_info()

        #with open(os.path.join(self.objdir, 'optimized.mk'), 'wb') as fh:
        #    self.generate_makefile(fh)

        for makefile in self.vanilla.makefiles():
            try:
                self.process_makefile(makefile)
            except:
                print 'Error processing %s' % makefile.filename
                traceback.print_exc()

        print 'Creating output directories'
        for path in sorted(self.output_directories):
            if not os.path.exists(path):
                os.makedirs(path, 0777)

        with open(os.path.join(self.objdir, 'main.mk'), 'wb') as fh:
            self.print_main_makefile(fh)

    def clean(self):
        self.vanilla.clean()

    def process_makefile(self, original):
        # TODO MozillaMakefile should use proper statements API.
        output_path = self.vanilla.output_path_from_makefile(original)

        strip_variables = set()
        splendid_path = os.path.join(os.path.dirname(output_path), 'splendid.mk')
        with open(splendid_path, 'wb') as fh:
            strip_variables = self.write_splendid_makefile(original, fh)

        self.splendid_files.add(splendid_path)

        # TODO Strip out variables we handle ourselves.
        makefile = Makefile(output_path)

        for statement in original.statements._statements:
            makefile.append(statement.statement)

        with open(output_path, 'wb') as fh:
            fh.write(makefile.to_source())

    def get_converted_path(self, path):
        """Convert a string filesystem path into its Makefile equivalent, with
        appropriate variable substitution."""
        if path[0:len(self.tree.object_directory)] == self.tree.object_directory:
            return '$(OBJECT_DIR)%s' % path[len(self.tree.object_directory):]
        elif path[0:len(self.tree.top_source_directory)] == self.tree.top_source_directory:
            return '$(TOP_SOURCE_DIR)%s' % path[len(self.tree.top_source_directory):]
        else:
            return path

    def write_splendid_makefile(self, makefile, fh):
        """Writes a splendid, non-recursive make file."""

        print >>fh, '# This file is automatically generated. Do NOT edit.'

        strip_variables = set()

        for obj in makefile.get_data_objects():
            method = None
            if isinstance(obj, data.ExportsInfo):
                method = self._write_exports
            elif isinstance(obj, data.XPIDLInfo):
                method = self._write_idl

            if method:
                strip_variables |= method(makefile, fh, obj)

    def _write_exports(self, makefile, fh, obj):
        # Install exported files into proper location. These are
        # typically header files.

        inc_dir = os.path.join(self.objdir, 'dist', 'include')

        directories = sorted(obj.output_directories)
        out_directories = [os.path.join(inc_dir, d) for d in directories]
        self.output_directories |= set(out_directories)
        print >>fh, 'CREATE_DIRS += %s' % ' '.join(out_directories)

        output_filenames = []

        for input_filename, output_leaf in obj.filenames.iteritems():
            output_directory = os.path.join(inc_dir,
                os.path.dirname(output_leaf))
            output_filename = os.path.join(inc_dir, output_leaf)
            output_filenames.append(output_filename)

            print >>fh, '%s: %s' % (output_filename, input_filename)
            print >>fh, '\t$(INSTALL) -R -m 644 "%s" "%s"\n' % (input_filename,
                output_directory)

        print >>fh, 'EXPORT_TARGETS += %s\n' % ' \\\n  '.join(output_filenames)
        print >>fh, 'PHONIES += EXPORT_TARGETS'

        return set()

    def _write_idl(self, makefile, fh, obj):
        # IDLs are copied to a common idl directory then they are processed.
        # The copying must complete before processing starts.

        idl_output_directory = os.path.join(self.objdir, 'dist', 'idl')
        header_output_directory = os.path.join(self.objdir, 'dist', 'include')

        for source in sorted(obj.sources):
            basename = os.path.basename(source)
            header_basename = os.path.splitext(basename)[0] + '.h'

            output_idl_path = os.path.join(idl_output_directory, basename)
            output_header_path = os.path.join(header_output_directory,
                header_basename)

            # Record the final destination of this IDL in a variable so that
            # variable can be used as a prerequisite.
            print >>fh, 'IDL_DIST_FILES += %s' % output_idl_path
            print >>fh, 'IDL_H_FILES += %s' % output_header_path
            print >>fh, ''

            # Install the original IDL file into the IDL directory.
            print >>fh, '%s: %s' % (output_idl_path, source)
            print >>fh, '\t$(INSTALL) -R -m 664 "%s" "%s"\n' % (source,
                idl_output_directory)
            print >>fh, ''

            # TODO write out IDL dependencies file via rule and hook up to
            # prereqs for IDL generation. This requires a bit more code to be
            # written. For now, we omit the dependencies, which is very wrong.
            idl_deps_path = os.path.join(self.objdir, 'deps',
                '%s.deps' % basename)

            print >>fh, '%s: $(IDL_DIST_FILES)' % output_header_path
            print >>fh, '\t$(IDL_GENERATE_HEADER) -o $@ %s' % output_idl_path
            print >>fh, ''

        return set()

    def print_main_makefile(self, fh):
        print >>fh, '# This file is automatically generated. Do NOT edit.'

        print >>fh, 'TOP_SOURCE_DIR := %s' % self.srcdir
        print >>fh, 'OBJECT_DIR := %s' % self.objdir

        print >>fh, 'DEPTH := .'
        print >>fh, 'topsrcdir := %s' % self.srcdir
        print >>fh, 'srcdir := %s' % self.srcdir
        print >>fh, 'include $(topsrcdir)/config/config.mk'

        print >>fh, 'default:'
        print >>fh, '\t-echo "Use mach to build with this file."; \\'
        print >>fh, '\texit 1;'
        print >>fh, '\n'

        for path in sorted(self.splendid_files):
            print >>fh, 'include %s' % path

        print >>fh, 'include $(TOP_SOURCE_DIR)/config/makefiles/nonrecursive.mk'

    ######################
    # CONTENT BELOW IS OLD
    ######################

    def _print_header(self, state):
        fh = state['fh']

        print >>fh, '# THIS FILE WAS AUTOMATICALLY GENERATED. DO NOT MODIFY BY HAND'
        print >>fh, 'TOP_SOURCE_DIR := %s' % self.tree.top_source_directory
        print >>fh, 'OBJECT_DIR := %s' % self.tree.object_directory
        print >>fh, 'DIST_DIR := $(OBJECT_DIR)/dist'
        print >>fh, 'DIST_INCLUDE_DIR := $(DIST_DIR)/include'
        print >>fh, 'DIST_IDL_DIR := $(DIST_DIR)/idl'
        print >>fh, 'TEMP_DIR := $(DIST_DIR)/tmp'
        print >>fh, 'COPY := cp'
        print >>fh, 'CXX := g++'
        print >>fh, ''

        # Import main build system variables.
        print >>fh, 'DEPTH := .'
        print >>fh, 'topsrcdir := %s' % self.srcdir
        print >>fh, 'srcdir := %s' % self.srcdir
        print >>fh, 'include $(topsrcdir)/config/config.mk'
        print >>fh, ''

        # The first defined target in a Makefile is the default one. The name
        # 'default' reinforces this.
        #print >>fh, 'default: export libraries\n'
        print >>fh, 'default:\n'

        print >>fh, 'export: distdirs\n'
        print >>fh, 'libraries: object_files\n'

        print >>fh, 'distdirs: $(DIST_DIR) $(DIST_INCLUDE_DIR)\n'

        state['phonies'] |= set(['default', 'libraries', 'distdirs'])

        # Directory creation targets
        print >>fh, '$(DIST_DIR) $(DIST_INCLUDE_DIR) $(TEMP_DIR):'
        print >>fh, '\t$(NSINSTALL_PY) -D -m 775 "$@"\n'

    def _print_footer(self, state):
        fh = state['fh']

        # Define .PHONY target with collected list
        print >>fh, '.PHONY: %s\n' % ' \\\n  '.join(state['phonies'])


    def _print_libraries(self, state):
        """Prints library targets."""

        fh = state['fh']

        object_filenames = []

        names = sorted(self.tree.libraries.keys())
        for name in names:
            # TODO calculate filenames properly

            library = self.tree.libraries[name]

            compiler_args = ['-c']
            compiler_args.extend(library['cxx_flags'])

            for define in library['defines']:
                compiler_args.append('-D%s' % define)

            for include in library['includes']:
                compiler_args.append('-I%s' % self.get_converted_path(include))

            for source in library['cpp_sources']:
                basename = os.path.basename(source)
                source_filename = '%s/%s' % (
                    self.get_converted_path(library['source_dir']),
                    source
                )
                target_filename = '%s/%s.o' % (
                    self.get_converted_path(library['output_dir']),
                    os.path.splitext(basename)[0]
                )

                print >>fh, '%s: %s' % ( target_filename, source_filename )
                print >>fh, '\t$(CXX) %s -o "%s" "%s"\n' % (
                    ' '.join(compiler_args), target_filename, source_filename
                )

                object_filenames.append(target_filename)

        object_filenames.sort()
        print >>fh, 'object_files: %s\n' % ' \\\n  '.join(object_filenames)
        state['phonies'].add('object_files')
