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
from . import extractor
from . import makefile

import os
import os.path
import subprocess
import traceback

class BuildSystem(object):
    """High-level interface to the build system."""

    __slots__ = (
        # BuildSystemExtractor instance
        'bse',

        # Method that gets invoked any time an action is performed.
        'callback',

        # config.BuildConfig instance
        'config',
    )

    def __init__(self, conf, callback=None):
        """Construct an instance from a source and target directory."""
        assert(isinstance(conf, config.BuildConfig))

        self.config = conf
        self.bse = extractor.BuildSystemExtractor(conf)
        self.callback = callback

    def build(self):
        if not self.bse.is_configured:
            self.configure()

        # TODO make conditional
        self.generate_makefiles()

    def configure(self):
        """Runs configure on the build system."""

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

        # Tell configure not to load a .mozconfig.
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

        self.bse.refresh_configure_state()

    def generate_makefiles(self):
        """Generate Makefile's into configured object tree."""

        if not self.bse.is_configured:
            self.configure()

        self.run_callback('generate_makefile_begin', {},
                          'Beginning generation of Makefiles',
                          important=True)

        conversion = self.config.makefile_conversion
        apply_rewrite = conversion == 'rewrite'
        strip_false_conditionals = conversion in ('prune', 'optimized')

        for relative, path in self.bse.source_directory_template_files():
            try:
                full = os.path.join(self.config.source_directory, relative, path)

                self.run_callback('makefile-generate', {'path': full},
                                  'Generating makefile: {path}')

                autoconf = self.bse.autoconf_for_path(relative)
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

        def missing_callback(variable):
            self.run_callback(
                'makefile_substitution_missing',
                {'path': os.path.join(relative_path, out_basename), 'var': variable},
                'Missing source variable for substitution: {var} in {path}',
                error=True)

        m = extractor.MozillaMakefile(input_path,
                                      relative_directory=os.path.dirname(relative_path),
                                      directory=output_directory)
        m.perform_substitutions(self.bse, callback_on_missing=missing_callback)

        if strip_false_conditionals:
            m.statements.strip_false_conditionals()
        elif apply_rewrite:
            # This has the side-effect of populating the StatementCollection,
            # which will cause lines to come from it when we eventually write
            # out the content.
            lines = m.statements.lines()

            # Perform verification that the rewritten file is equivalent to the
            # original. This is present for mostly testing and verification
            # purposes. For API reasons, it should be controlled by a named
            # argument. It should probably be left off by default because it
            # is expensive (doubles makefile generation time).
            rewritten = makefile.StatementCollection(buf='\n'.join(lines),
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

        with open(output_path, 'wb') as output:
            for line in m.lines():
                print >>output, line

        self.run_callback(
            'generate_makefile_success',
            {'path': os.path.join(relative_path, out_basename)},
            'Generated Makefile {path}')

    def run_callback(self, action, params, formatter,
                     important=False, error=False):
        if self.callback:
            self.callback(action, params, formatter,
                          important=important, error=error)
