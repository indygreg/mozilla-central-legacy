# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file is deprecated. Move along.

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
from mozbuild.buildconfig.makefile import MakefileCollection
from mozbuild.buildconfig.makefile import StatementCollection
from mozbuild.buildconfig.mozillamakefile import MozillaMakefile

class BuildSystemExtractor(Base):
    """High-level entity that is used to "parse" the build config

    This is the interface that turns Makefile.in's and configure output into
    data structures.

    This is the gateway to creating a new build backend.
    """

    __slots__ = (
        # Holds dictionary of autoconf values for different paths.
        'autoconfs',

        # BuildConfig instance
        'config',

        # MakefileCollection for the currently loaded Makefiles
        'makefiles',

        # logging.Logger instance
        'logger',
    )

    def __init__(self, config):
        Base.__init__(self, config)

    ###### OLD API BELOW

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

    def load_all_object_directory_makefiles(self):
        """Convenience method to load all Makefiles in the object directory.

        This pulls in *all* the Makefiles. You probably want to pull in a
        limited set instead.
        """
        for reldir, name, type in self.object_directory_build_files():
            if type != self.BUILD_FILE_MAKEFILE:
                continue

            path = os.path.join(self.config.object_directory, reldir, name)
            m = MozillaMakefile(path)
            self.makefiles.add(m)

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
    def sha1_file_hash(filename):
        h = hashlib.sha1()
        with open(filename, 'rb') as fh:
            while True:
                data = fh.read(8192)
                if not data:
                    break

                h.update(data)

        return h.hexdigest()
