# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Mozilla build system.
#
# The Initial Developer of the Original Code is Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#  Gregory Szorc <gps@mozilla.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisiwons above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

# This file contains a high-level class, BuildSystem, for interacting with
# the Mozilla build system.

from . import config
from . import makefile

import hashlib
import os
import os.path
import subprocess
import traceback

class BuildSystem(object):
    """High-level interface to the build system."""

    # Ideally no paths should be ignored, but alas.
    IGNORED_PATHS = (
        # We ignore libffi because we have no way of producing the files from the
        # .in because configure doesn't give us an easily parseable file
        # containing the defines.
        'js/src/ctypes/libffi',
    )

    # Paths in object directory that are produced by configure. We keep
    # track of these paths and look for changes, etc.
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

    # Files produced by configure that we don't care about
    CONFIGURE_IGNORE_FILES = (
        'js/src/config.log',
        'js/src/unallmakefiles',
        'nsprpub/config.log',
        'config.cache',
        'config.log',
        'unallmakefiles',
    )

    CONFIGURE_IGNORE_DIRECTORIES = (
        'js/src/ctypes/libffi',
    )

    __slots__ = (
        # Mapping of identifiers to autoconf.mk data.Makefile instances
        'autoconfs',

        # Method that gets invoked any time an action is performed.
        'callback',

        # config.BuildConfig instance
        'config',

        # whether the object directory has been configured
        'is_configured',

        # Holds cached state for configure output
        'configure_state',
    )

    def __init__(self, conf, callback=None):
        """Construct an instance from a source and target directory."""
        assert(isinstance(conf, config.BuildConfig))

        self.config          = conf
        self.callback        = callback
        self.autoconfs       = None
        self.is_configured   = False
        self.configure_state = None

    @property
    def have_state(self):
        return self.autoconfs is not None and self.configure_state is not None

    def build(self):
        if not self.is_configured:
            self.configure()

        # TODO make conditional
        self.generate_makefiles()

    def refresh_state(self):
        self.autoconfs = {}
        if self.configure_state is None:
            self.configure_state = {
                'files': {}
            }

        def get_variable_map(filename):
            d = {}

            allowed_types = (
                makefile.StatementCollection.VARIABLE_ASSIGNMENT_SIMPLE,
                makefile.StatementCollection.VARIABLE_ASSIGNMENT_RECURSIVE
            )

            statements = makefile.StatementCollection(filename=filename)

            # We evaluate ifeq's because the config files /should/ be
            # static. We don't rewrite these, so there is little risk.
            statements.strip_false_conditionals(evaluate_ifeq=True)

            for statement, conditions, name, value, type in statements.variable_assigments():
                if len(conditions):
                    raise Exception(
                        'Conditional variable assignment encountered (%s) in autoconf file: %s' % (
                            name, statement.location ))

                if name in d:
                    if type not in allowed_types:
                        raise Exception('Variable assigned multiple times in autoconf file: %s' % name)

                d[name] = value

            return d

        self.is_configured = True

        for path in self.CONFIGURE_MANAGED_FILES:
            full = os.path.join(self.config.object_directory, path)

            # Construct defined variables from autoconf.mk files
            if path[-len('config/autoconf.mk'):] == 'config/autoconf.mk':
                if os.path.exists(full):
                    k = path[0:-len('config/autoconf.mk')].rstrip('/')
                    self.autoconfs[k] = get_variable_map(full)
                else:
                    self.is_configured = False

            if not os.path.exists(full) and path in self.configure_state['files']:
                raise Exception('File managed by configure has disappeared. Re-run configure: %s' % path)

            if os.path.exists(full):
                self.configure_state['files'][path] = {
                    'sha1': self._sha1_file_hash(full),
                    'mtime': os.path.getmtime(full),
                }

    def configure(self):
        """Runs configure on the build system."""

        if not self.have_state:
            self.refresh_state()

        # TODO regenerate configure's from configure.in's if needed

        # Create object directory if it doesn't exist
        if not os.path.exists(self.config.object_directory):
            self.run_callback('create_object_directory',
                              {'dir':self.config.object_directory},
                              'Creating object directory {dir}',
                              important=True)

            os.makedirs(self.config.object_directory)

        configure_path = os.path.join(self.config.source_directory, 'configure')

        env = {}
        for k, v in os.environ.iteritems():
            env[k] = v

        # We tell configure via an environment variable not to load a
        # .mozconfig
        env['IGNORE_MOZCONFIG'] = '1'

        # Tell configure scripts not to generate Makefiles, as we do that.
        env['DONT_GENERATE_MAKEFILES'] = '1'

        args = self.config.configure_args

        self.run_callback('configure_begin', {'args': args},
                          formatter='Starting configure: {args}',
                          important=True)

        p = subprocess.Popen(
            args,
            cwd=self.config.object_directory,
            executable=configure_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        while True:
            for line in p.stdout:
                self.run_callback('configure_output', {'line': line.strip()},
                                  '{line}', important=False)

            if p.poll() is not None:
                break

        result = p.wait()

        if result != 0:
            self.run_callback('configure_error', {'resultcode': result},
                              'Configure Error: {resultcode}',
                              error=True)
        else:
            self.run_callback('configure_finish', {},
                              'Configure finished successfully',
                              important=True)

        self.refresh_state()

    def generate_makefiles(self):
        """Generate Makefile's into configured object tree."""

        if not self.have_state:
            self.refresh_state()

        if not self.is_configured:
            self.configure()

        self.run_callback('generate_makefile_begin', {},
                          'Beginning generation of Makefiles',
                          important=True)

        conversion = self.config.makefile_conversion
        apply_rewrite = conversion == 'rewrite'
        strip_false_conditionals = conversion in ('prune', 'optimized')

        # PyMake's cache only holds 15 items. We assume we have the resources
        # (because we are building m-c after all) and keep ALL THE THINGS in
        # memory.
        statements_cache = {}

        for (relative, path) in self.source_directory_template_files():
            try:
                full = os.path.join(self.config.source_directory, relative, path)

                autoconf = self._get_autoconf_for_file(relative)
                self.generate_makefile(
                    relative, path, translation_map=autoconf,
                    strip_false_conditionals=strip_false_conditionals,
                    apply_rewrite=apply_rewrite)
            except:
                self.run_callback(
                    'generate_makefile_exception',
                    {'path': os.path.join(relative, path), 'exception': traceback.format_exc()},
                    'Exception when processing Makefile {path}\n{exception}',
                    error=True)

        self.run_callback('generate_makefile_finish', {},
                          'Finished generation of Makefiles',
                          important=True)

    def generate_makefile(self, relative_path, filename, translation_map=None,
                          strip_false_conditionals=False, apply_rewrite=False):
        """Generate a Makefile from an input file.

        Generation options can be toggled by presence of arguments:

          translation_map
              If defined as a dictionary, strings of form "@varname@" will be
              replaced by the value contained in the passed dictionary. If this
              argument is None (the default), no translation will occur.

          strip_false_conditionals
              If True, conditionals evaluated to false will be stripped from the
              Makefile. This implies apply_rewrite=True

          apply_rewrite
             If True, the Makefile will be rewritten from PyMake's parser
             output. This will lose formatting of the original file. However,
             the produced file should be functionally equivalent to the
             original. This argument likely has little use in normal
             operation. It is exposed to debug the functionality of the
             rewriting engine.
        """
        if strip_false_conditionals:
            apply_rewrite = True

        input_path = os.path.join(self.config.source_directory, relative_path, filename)

        out_basename = filename
        if out_basename[-3:] == '.in':
            out_basename = out_basename[0:-3]

        output_path = os.path.join(self.config.object_directory,
                                   relative_path,
                                   out_basename)

        # Create output directory
        output_directory = os.path.dirname(output_path)

        if not os.path.exists(output_directory):
            os.makedirs(output_directory)
            self.run_callback('mkdir', {'dir': output_directory},
                              'Created directory: {dir}')

        managed_path = None
        for managed in self.MANAGED_PATHS:
            if relative_path[0:len(managed)] == managed:
                managed_path = managed
                break

        # We assume these will be calculated at least once b/c they
        # are common.
        top_source_directory = self.config.source_directory
        if managed_path is not None:
            top_source_directory = os.path.join(top_source_directory,
                                                managed_path)

        source_directory = os.path.join(self.config.source_directory,
                                        relative_path)

        mapping = {}
        for k, v in translation_map.iteritems():
            mapping[k] = v

        mapping['srcdir']     = source_directory
        mapping['top_srcdir'] = top_source_directory
        mapping['configure_input'] = 'Generated automatically from Build Splendid'

        def missing_callback(variable):
            self.run_callback(
                'makefile_substitution_missing',
                {'path': os.path.join(relative_path, out_basename), 'var': variable},
                'Missing source variable for substitution: {var} in {path}',
                error=True)

        m = makefile.Makefile(input_path, directory=output_directory)
        m.perform_substitutions(mapping, callback_on_missing=missing_callback)

        if strip_false_conditionals:
            m.statements.strip_false_conditionals()
        elif apply_rewrite:
            # This has the side-effect of populating the StatementCollection,
            # which will cause lines to come from it.
            lines = m.statements.lines

        with open(output_path, 'wb') as output:
            for line in m.lines():
                print >>output, line

        self.run_callback(
            'generate_makefile_success',
            {'path': os.path.join(relative_path, out_basename)},
            'Generated Makefile {path}')

    def source_directory_template_files(self):
        """Obtain all template files from the source directory."""
        for relative, filename, type in self.source_directory_build_files():
            if type != self.BUILD_FILE_INPUT:
                continue

            if relative in self.IGNORED_PATHS:
                continue

            yield (relative, filename)

    def _get_autoconf_for_file(self, path):
        """Obtain an autoconf file for a relative path."""

        for managed in self.MANAGED_PATHS:
            if path[0:len(managed)] == managed:
                return self.autoconfs[managed]

        return self.autoconfs['']

    def _sha1_file_hash(self, filename):
        h = hashlib.sha1()
        with open(filename, 'rb') as fh:
            while True:
                data = fh.read(8192)
                if not data:
                    break

                h.update(data)

        return h.hexdigest()

    def run_callback(self, action, params, formatter,
                     important=False, error=False):
        if self.callback:
            self.callback(action, params, formatter,
                          important=important, error=error)
